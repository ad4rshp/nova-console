import asyncio
import threading
import time
from typing import Any

import httpx

from app.config import LLM_BACKEND_URL, VERSION
from app.database import db_get_settings, db_get_usage_metrics
from app.services.hardware import get_gpu_stats, get_ram_stats, get_storage_stats
from app.services.http_client import get_shared_client
from app.services.modelfile import read_modelfile
from app.services.resource_manager import global_resource_manager
from app.services.updater import check_for_updates

_model_cache_lock = threading.Lock()
_model_cache: dict[str, Any] = {
    "engine_name": "Local Inference Engine",
    "models": [],
    "models_ts": 0.0,
    "loaded": [],
    "loaded_ts": 0.0,
    "status": "offline",
}
MODEL_CACHE_TTL = 30.0
RUNNING_CACHE_TTL = 8.0


def invalidate_model_cache() -> None:
    """Invalidates the in-memory cache of models and running processes."""
    with _model_cache_lock:
        _model_cache["models_ts"] = 0.0
        _model_cache["loaded_ts"] = 0.0


async def detect_engine_type(
    url: str,
    client: httpx.AsyncClient | None = None,
    force_refresh: bool = False
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    """
    Auto-detects the running inference engine with caching:
    Available models are cached for 30s, active running models for 8s.
    Supports Ollama, LM Studio, vLLM, llama-server, LocalAI, or any OpenAI-compatible provider.
    """
    now = time.time()
    with _model_cache_lock:
        models_fresh = (now - _model_cache["models_ts"] < MODEL_CACHE_TTL) and bool(_model_cache["models"])
        loaded_fresh = (now - _model_cache["loaded_ts"] < RUNNING_CACHE_TTL)
        if not force_refresh and models_fresh and loaded_fresh:
            return (
                _model_cache["engine_name"],
                list(_model_cache["models"]),
                list(_model_cache["loaded"]),
                _model_cache["status"],
            )

    if client is None:
        client = get_shared_client()

    models: list[dict[str, Any]] = []
    loaded: list[dict[str, Any]] = []
    engine_name = "Local Inference Engine"
    status = "offline"

    # 1. Check for Ollama endpoints (/api/tags and /api/ps)
    try:
        tags_res = await client.get(f"{url}/api/tags", timeout=2.5)
        if tags_res.status_code == 200:
            models = tags_res.json().get("models", [])
            engine_name = "Ollama"
            status = "online"

            try:
                ps_res = await client.get(f"{url}/api/ps", timeout=2.0)
                if ps_res.status_code == 200:
                    loaded = ps_res.json().get("models", [])
            except Exception:
                pass

            with _model_cache_lock:
                _model_cache["engine_name"] = engine_name
                _model_cache["models"] = models
                _model_cache["models_ts"] = now
                _model_cache["loaded"] = loaded
                _model_cache["loaded_ts"] = now
                _model_cache["status"] = status

            return engine_name, models, loaded, status
    except Exception:
        pass

    # 2. Check universal OpenAI /v1/models endpoint (LM Studio, vLLM, llama-server, LocalAI)
    try:
        v1_res = await client.get(f"{url}/v1/models", timeout=2.5)
        if v1_res.status_code == 200:
            data = v1_res.json()
            raw_models = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for item in raw_models:
                m_id = item.get("id") or item.get("name") or "unknown"
                models.append({
                    "name": m_id,
                    "model": m_id,
                    "details": item.get("details", {}),
                    "size": item.get("size", 0)
                })
            status = "online"

            # Determine specific engine signature
            if "1234" in url or "lmstudio" in str(v1_res.headers).lower():
                engine_name = "LM Studio"
            elif "8000" in url or "vllm" in str(v1_res.headers).lower():
                engine_name = "vLLM"
            elif "8080" in url or "localai" in str(v1_res.headers).lower():
                engine_name = "LocalAI"
            else:
                engine_name = "OpenAI-Compatible Engine"

            with _model_cache_lock:
                _model_cache["engine_name"] = engine_name
                _model_cache["models"] = models
                _model_cache["models_ts"] = now
                _model_cache["loaded"] = loaded
                _model_cache["loaded_ts"] = now
                _model_cache["status"] = status

            return engine_name, models, loaded, status
    except Exception:
        pass

    with _model_cache_lock:
        _model_cache["status"] = "offline"

    return engine_name, models, loaded, "offline"


async def get_dashboard_state(force_refresh: bool = False) -> dict[str, Any]:
    client = get_shared_client()
    engine_name, models, loaded, status = await detect_engine_type(LLM_BACKEND_URL, client, force_refresh=force_refresh)

    ram, gpu, storage, mf, settings, usage = await asyncio.gather(
        asyncio.to_thread(get_ram_stats),
        asyncio.to_thread(get_gpu_stats),
        asyncio.to_thread(get_storage_stats),
        asyncio.to_thread(read_modelfile),
        asyncio.to_thread(db_get_settings),
        asyncio.to_thread(db_get_usage_metrics),
    )

    saved_ctx = int(mf["parameters"].get("num_ctx", 2048))
    loaded_ctx = None
    loaded_model_name = None

    # Inspect loaded models for CPU/GPU split offloading and active context
    split_offload_info = None
    for m in loaded:
        m_name = m.get("name") or m.get("model") or ""
        total_size = m.get("size", 0)
        vram_size = m.get("size_vram", 0)

        # Detect if model is split between GPU VRAM and CPU RAM
        if total_size > 0 and vram_size < total_size:
            gpu_pct = round((vram_size / total_size) * 100)
            cpu_pct = 100 - gpu_pct
            split_offload_info = {
                "model": m_name,
                "gpu_pct": gpu_pct,
                "cpu_pct": cpu_pct,
                "vram_mb": round(vram_size / (1024 * 1024)),
                "total_mb": round(total_size / (1024 * 1024))
            }

        if m_name.startswith("nova") or not loaded_ctx:
            loaded_ctx = m.get("context_length")
            loaded_model_name = m_name

    ram_pct = ram.get("percent", 0)
    vram_pct = gpu.get("vram_percent", 0) if gpu else 0
    active_ctx = loaded_ctx or saved_ctx

    # Advanced Hardware Strain & Compatibility Engine:
    # 1. Critical Strain: RAM >= 85% or VRAM >= 88% with active context > 4096
    # 2. Split Offload Bottleneck: Model is split offloaded (CPU/GPU) causing memory bandwidth throttling
    # 3. Context Mismatch: Configured Modelfile != active model in VRAM
    is_hardware_overload = bool((ram_pct >= 85 or vram_pct >= 88) and active_ctx > 4096)
    is_pending_rebuild = bool((loaded_ctx is not None and saved_ctx != loaded_ctx) or is_hardware_overload)

    # Determine recommended preset based on hardware headroom
    vram_total_mb = float(gpu.get("total_mb", 0)) if gpu else 0
    recommended_preset = "medium"
    if vram_total_mb > 0 and vram_total_mb < 5500:
        recommended_preset = "low"
    elif vram_total_mb >= 10000:
        recommended_preset = "high"

    diagnostics: list[dict[str, Any]] = []
    if status == "offline":
        diagnostics.append({
            "level": "error",
            "title": "Inference Engine Offline",
            "message": f"Cannot reach local LLM server at {LLM_BACKEND_URL}. Ensure your engine (Ollama, LM Studio, vLLM, or llama-server) is running.",
            "action": "Start your local engine or set NOVA_BACKEND_URL in your environment.",
        })
    elif not models:
        diagnostics.append({
            "level": "warning",
            "title": "No Models Found",
            "message": f"Connected to {engine_name}, but no models are loaded or pulled.",
            "action": "Load or pull a model in your local engine to begin.",
        })

    # High-Priority Critical Strain Alert
    if is_hardware_overload:
        target_ctx = 2048 if (ram_pct >= 90 or vram_pct >= 92) else 4096
        preset_name = "low" if target_ctx == 2048 else "medium"
        diagnostics.append({
            "level": "error",
            "title": "Hardware Strain Alert: High Memory Pressure",
            "message": f"System under pressure ({ram_pct}% RAM · {vram_pct}% VRAM). Active context ({active_ctx:,} tokens) risks Out-Of-Memory (OOM) crashes or heavy disk paging.",
            "action": f"Apply {preset_name.title()} Preset ({target_ctx:,} ctx) to relieve memory immediately.",
            "suggested_ctx": str(target_ctx),
            "suggested_preset": preset_name
        })
    # CPU/GPU Split Performance Alert
    elif split_offload_info and split_offload_info["cpu_pct"] >= 15:
        cpu_p = split_offload_info["cpu_pct"]
        gpu_p = split_offload_info["gpu_pct"]
        diagnostics.append({
            "level": "warning",
            "title": "Hardware Advisory: CPU/GPU Split Offloading",
            "message": f"'{split_offload_info['model']}' is split: {cpu_p}% CPU RAM / {gpu_p}% GPU VRAM. Prompt evaluation is memory-bandwidth throttled by system RAM.",
            "action": "Downscale context window to Low (2K) or Medium (4K) to fit 100% inside GPU VRAM for maximum speed.",
            "suggested_ctx": "2048" if vram_pct > 75 else "4096",
            "suggested_preset": "low" if vram_pct > 75 else "medium",
            "split_info": split_offload_info
        })
    # Modelfile Context Mismatch
    elif is_pending_rebuild:
        diagnostics.append({
            "level": "warning",
            "title": "Pending Parameter Sync: Context Mismatch",
            "message": f"Saved Modelfile specifies {saved_ctx:,} context tokens, but active model in VRAM is running with {loaded_ctx:,} tokens.",
            "action": f"Click 'Rebuild Nova' below to compile and apply the saved {saved_ctx:,}-token context window.",
            "suggested_ctx": str(saved_ctx)
        })
    # High System RAM Warning
    elif ram_pct >= 88:
        diagnostics.append({
            "level": "warning",
            "title": "High Memory Pressure",
            "message": f"System RAM is at {ram_pct}%. Operating near capacity may cause sluggish responses or page swapping.",
            "action": "Close idle background applications or evict unused models from memory.",
        })
    # Optimal Hardware Headroom
    elif status == "online" and loaded and not split_offload_info:
        diagnostics.append({
            "level": "info",
            "title": "Hardware Optimal: 100% GPU Offload",
            "message": f"Loaded models are fully contained in VRAM ({vram_pct}% VRAM · {ram_pct}% RAM). Full memory bandwidth active for high TPS.",
            "action": "System is performing at peak efficiency.",
        })

    # Asynchronously check for release updates (cached in memory, 0 MB background RAM)
    update_info = await check_for_updates()
    resource_profile = global_resource_manager.get_hardware_profile()

    return {
        "status": status,
        "version": VERSION,
        "update": update_info,
        "engine": {
            "name": engine_name,
            "url": LLM_BACKEND_URL
        },
        "models": models,
        "loaded": loaded,
        "ram": ram,
        "gpu": gpu,
        "storage": storage,
        "usage": usage,
        "settings": settings,
        "modelfile": mf,
        "modelfile_status": {
            "saved_context": saved_ctx,
            "loaded_context": loaded_ctx,
            "loaded_model_name": loaded_model_name,
            "pending_rebuild": is_pending_rebuild,
            "hardware_overload": is_hardware_overload,
            "recommended_preset": recommended_preset,
            "split_offload": split_offload_info,
        },
        "resource_profile": resource_profile,
        "diagnostics": diagnostics,
    }

