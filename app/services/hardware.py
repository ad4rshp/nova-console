import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

# Cache for storage metrics to prevent disk thrashing on frequent dashboard polling
_STORAGE_CACHE: dict[str, Any] = {
    "timestamp": 0.0,
    "model_dir_gb": 0.0,
    "path": ""
}
STORAGE_CACHE_TTL = 60.0  # Recalculate model directory size at most once per 60 seconds

def get_ram_stats() -> dict[str, Any]:
    """
    Returns actual measured host RAM statistics without fabricating data.
    """
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total / (1024 ** 3), 1),
            "used_gb": round(vm.used / (1024 ** 3), 1),
            "percent": int(vm.percent),
            "status": "active"
        }
    except Exception:
        # Fallback for Windows native API without psutil
        if platform.system() == "Windows":
            try:
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    total = stat.ullTotalPhys / (1024 ** 3)
                    used = (stat.ullTotalPhys - stat.ullAvailPhys) / (1024 ** 3)
                    return {
                        "total_gb": round(total, 1),
                        "used_gb": round(used, 1),
                        "percent": int(stat.dwMemoryLoad),
                        "status": "active"
                    }
            except Exception:
                pass

        # Return unavailable rather than fabricating dummy values
        return {
            "total_gb": None,
            "used_gb": None,
            "percent": None,
            "status": "unavailable"
        }

def get_gpu_stats() -> dict[str, Any]:
    """
    Detects GPU hardware and VRAM consumption across NVIDIA CUDA, Apple Metal, AMD ROCm,
    or falls back to CPU mode with honest measurement indicators.
    """
    sys_name = platform.system()

    # 1. Check NVIDIA GPU via nvidia-smi
    nvsmi = shutil.which("nvidia-smi")
    if nvsmi:
        try:
            cmd = [
                nvsmi,
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
                if lines:
                    line = lines[0]
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        try:
                            used_mb = float(parts[1])
                            total_mb = float(parts[2])
                            pct = int((used_mb / total_mb * 100)) if total_mb > 0 else 0
                        except (ValueError, ZeroDivisionError):
                            used_mb, total_mb, pct = 0.0, 0.0, 0

                        return {
                            "type": "nvidia",
                            "name": parts[0] + (f" (+{len(lines)-1} more)" if len(lines) > 1 else ""),
                            "used_mb": str(int(used_mb)),
                            "total_mb": str(int(total_mb)),
                            "utilization": parts[3],
                            "vram_percent": pct,
                            "gpu_count": len(lines),
                            "memory_category": "dedicated_vram",
                            "is_dedicated_vram": True,
                            "memory_description": "Dedicated GPU VRAM",
                            "status": "active"
                        }
        except Exception:
            pass

    # 2. Check Apple Silicon (macOS Metal / Unified Memory)
    if sys_name == "Darwin":
        try:
            model_res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            chip_name = model_res.stdout.strip()
            if not chip_name or "Apple" not in chip_name:
                model_res = subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=2)
                chip_name = f"Apple Silicon ({model_res.stdout.strip()})"

            ram = get_ram_stats()
            if ram.get("status") == "active" and ram.get("total_gb") is not None:
                return {
                    "type": "apple_metal",
                    "name": chip_name or "Apple Silicon (Metal)",
                    "used_mb": str(int(ram["used_gb"] * 1024)),
                    "total_mb": str(int(ram["total_gb"] * 1024)),
                    "utilization": str(ram["percent"]),
                    "vram_percent": ram["percent"],
                    "unified_memory": True,
                    "memory_category": "unified_memory",
                    "is_dedicated_vram": False,
                    "memory_description": "Apple Unified System Memory (Shared across CPU/GPU)",
                    "status": "active"
                }
        except Exception:
            pass

    # 3. Check AMD ROCm (Linux / Windows)
    rocm_smi = shutil.which("rocm-smi")
    if rocm_smi:
        try:
            cmd = [rocm_smi, "--showuse", "--showmeminfo", "vram", "--csv"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
                # Parse ROCm CSV if headers present
                used_mb, total_mb, pct = None, None, None
                for line in lines[1:]:  # skip header
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        try:
                            used_mb = str(int(float(parts[1]) / (1024 * 1024)))
                            total_mb = str(int(float(parts[2]) / (1024 * 1024)))
                            pct = int(float(parts[1]) / float(parts[2]) * 100) if float(parts[2]) > 0 else 0
                        except Exception:
                            pass
                        break

                return {
                    "type": "amd_rocm",
                    "name": "AMD Radeon (ROCm)",
                    "used_mb": used_mb or "N/A",
                    "total_mb": total_mb or "N/A",
                    "utilization": str(pct) if pct is not None else "N/A",
                    "vram_percent": pct if pct is not None else 0,
                    "memory_category": "dedicated_vram",
                    "is_dedicated_vram": True,
                    "memory_description": "Dedicated GPU VRAM",
                    "status": "active" if total_mb else "unavailable"
                }
        except Exception:
            pass

    # 4. CPU-Only / Integrated Graphics Fallback
    ram = get_ram_stats()
    cpu_cores = os.cpu_count() or 4
    if ram.get("status") == "active" and ram.get("total_gb") is not None:
        return {
            "type": "cpu_only",
            "name": f"CPU Mode ({cpu_cores} Cores)",
            "used_mb": str(int(ram["used_gb"] * 1024)),
            "total_mb": str(int(ram["total_gb"] * 1024)),
            "utilization": str(ram["percent"]),
            "vram_percent": ram["percent"],
            "is_cpu_mode": True,
            "memory_category": "system_ram_shared",
            "is_dedicated_vram": False,
            "memory_description": "Shared Host System RAM (No Dedicated GPU)",
            "status": "active"
        }

    return {
        "type": "unknown",
        "name": f"CPU Mode ({cpu_cores} Cores)",
        "used_mb": "N/A",
        "total_mb": "N/A",
        "utilization": "N/A",
        "vram_percent": 0,
        "is_cpu_mode": True,
        "memory_category": "system_ram_shared",
        "is_dedicated_vram": False,
        "memory_description": "Shared Host System RAM (Unavailable)",
        "status": "unavailable"
    }

def get_storage_stats() -> dict[str, Any]:
    """
    Returns storage capacity and cached model directory footprint.
    Cached with a TTL to prevent repeated recursive directory traversals.
    """
    global _STORAGE_CACHE
    now = time.perf_counter()

    home = Path.home()
    ollama_dir = None
    if "OLLAMA_MODELS" in os.environ:
        ollama_dir = Path(os.environ["OLLAMA_MODELS"])
    else:
        candidates = [
            home / ".ollama" / "models",
            home / "AppData" / "Local" / "Programs" / "Ollama" / "models",
            Path("/usr/share/ollama/.ollama/models")
        ]
        for c in candidates:
            if c.exists():
                ollama_dir = c
                break

    if not ollama_dir or not ollama_dir.exists():
        ollama_dir = home / ".ollama" / "models"

    model_dir_gb = 0.0
    # Use cached size if within TTL
    if (now - _STORAGE_CACHE["timestamp"] < STORAGE_CACHE_TTL) and _STORAGE_CACHE["path"] == str(ollama_dir):
        model_dir_gb = _STORAGE_CACHE["model_dir_gb"]
    else:
        if ollama_dir.exists():
            try:
                total_bytes = sum(f.stat().st_size for f in ollama_dir.rglob("*") if f.is_file())
                model_dir_gb = round(total_bytes / (1024 ** 3), 1)
            except Exception:
                model_dir_gb = 0.0
        _STORAGE_CACHE["timestamp"] = now
        _STORAGE_CACHE["model_dir_gb"] = model_dir_gb
        _STORAGE_CACHE["path"] = str(ollama_dir)

    target_disk = ollama_dir if ollama_dir.exists() else home
    try:
        disk_free_gb = round(shutil.disk_usage(target_disk).free / (1024 ** 3), 1)
    except Exception:
        disk_free_gb = 0.0

    return {
        "model_dir_gb": model_dir_gb,
        "disk_free_gb": disk_free_gb,
        "path": str(ollama_dir)
    }
