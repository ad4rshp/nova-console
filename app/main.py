import json
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import STATIC_DIR, BASE_DIR, LLM_BACKEND_URL, DEFAULT_MODEL
from app.database import (
    init_db,
    db_get_settings,
    db_set_setting,
    db_get_recent_requests,
    db_get_usage_summary,
    db_save_chat_message,
    db_get_chat_history,
    db_clear_chat_history,
    db_record_request,
)
from app.services.hardware import get_ram_stats, get_gpu_stats, get_storage_stats
from app.services.modelfile import read_modelfile, update_modelfile, rebuild_nova_model, evict_model_vram
from app.services.llm_engine import get_dashboard_state
from app.services.terminal import assess_command_risk, run_system_command
from app.services.updater import check_for_updates

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database on startup
    init_db()
    yield

app = FastAPI(
    title="Nova Console API",
    description="Neumorphic Local AI Workstation & Universal LLM Proxy",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Assets Directory (/static/css, /static/js)
static_path = STATIC_DIR / "static"
if not static_path.exists():
    static_path = BASE_DIR / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# --- Pydantic Schemas ---
class SettingsPayload(BaseModel):
    think: bool | None = None
    save_chat_history: bool | None = None
    preview_thinking: str | None = None
    theme: str | None = None

class ModelfilePayload(BaseModel):
    system_prompt: str | None = None
    num_ctx: float | int | str | None = None
    num_predict: float | int | str | None = None
    temperature: float | int | str | None = None
    top_k: float | int | str | None = None
    top_p: float | int | str | None = None
    repeat_penalty: float | int | str | None = None

class UnloadPayload(BaseModel):
    model: str

class ProposeCommandPayload(BaseModel):
    command: str

class ExecuteCommandPayload(BaseModel):
    command: str
    working_dir: str | None = None
    approved: bool

# --- Frontend HTML Delivery ---
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    dashboard_file = STATIC_DIR / "dashboard.html"
    if not dashboard_file.exists():
        dashboard_file = BASE_DIR / "dashboard.html"
    if not dashboard_file.exists():
        raise HTTPException(status_code=404, detail="dashboard.html not found")
    return HTMLResponse(content=dashboard_file.read_text(encoding="utf-8"))

# --- Core Dashboard API ---
@app.get("/api/dashboard")
async def get_dashboard():
    return await get_dashboard_state()

@app.get("/api/check-update")
async def check_update_endpoint(force: bool = False):
    return await check_for_updates(force=force)

@app.get("/api/history")
async def get_history():
    return db_get_recent_requests(limit=100)

@app.get("/api/usage-summary")
async def get_usage_summary():
    return db_get_usage_summary()

@app.get("/api/chat-history")
async def get_chat_history():
    return db_get_chat_history()

@app.post("/api/clear-chat-history")
async def clear_chat_history():
    db_clear_chat_history()
    return {"ok": True, "message": "Chat history cleared."}

@app.post("/api/settings")
async def update_settings(payload: dict[str, Any]):
    for k, v in payload.items():
        db_set_setting(k, v)
    return db_get_settings()

@app.post("/api/modelfile")
async def update_modelfile_endpoint(payload: dict[str, Any]):
    try:
        return update_modelfile(payload)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

@app.post("/api/rebuild-nova")
async def rebuild_nova_endpoint():
    return await rebuild_nova_model(model_tag="nova")

@app.post("/api/unload")
async def unload_endpoint(payload: UnloadPayload):
    try:
        await evict_model_vram(payload.model)
        return {"ok": True, "message": f"{payload.model} evicted from VRAM."}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

# --- Terminal Command Execution Endpoints ---
@app.post("/api/terminal/propose")
async def propose_terminal_command(payload: ProposeCommandPayload):
    assessment = assess_command_risk(payload.command)
    return {"command": payload.command, **assessment}

@app.post("/api/terminal/execute")
async def execute_terminal_command(payload: ExecuteCommandPayload):
    if not payload.approved:
        return JSONResponse(status_code=403, content={"ok": False, "error": "Execution declined: user approval required."})
    return run_system_command(payload.command, working_dir=payload.working_dir, approved=True)

# --- Streaming Chat with Local Engine ---
@app.post("/api/dashboard-chat")
async def dashboard_chat(request: Request):
    payload = await request.json()
    model = payload.get("model", DEFAULT_MODEL)
    messages = payload.get("messages", [])
    images = payload.get("images", [])
    if not messages and "prompt" in payload:
        messages = [{"role": "user", "content": payload["prompt"]}]

    if images and messages and messages[-1].get("role") == "user":
        messages[-1]["images"] = images

    think = bool(payload.get("think", False))

    if messages and messages[-1].get("role") == "user":
        db_save_chat_message("user", messages[-1].get("content", ""), "", model, images=images)

    async def stream_generator() -> AsyncGenerator[str, None]:
        start_time = time.perf_counter()
        full_content = ""
        full_thinking = ""
        prompt_tokens = 0
        output_tokens = 0

        ollama_req = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": think
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                # Try native /api/chat first, fallback to standard /v1/chat/completions
                chat_url = f"{LLM_BACKEND_URL}/api/chat"
                async with client.stream("POST", chat_url, json=ollama_req) as response:
                    async for chunk in response.aiter_lines():
                        if not chunk.strip():
                            continue
                        yield chunk + "\n"
                        try:
                            data = json.loads(chunk)
                            msg = data.get("message", {})
                            if msg.get("content"):
                                full_content += msg["content"]
                            if msg.get("thinking"):
                                full_thinking += msg["thinking"]
                            if data.get("prompt_eval_count"):
                                prompt_tokens = data["prompt_eval_count"]
                            if data.get("eval_count"):
                                output_tokens = data["eval_count"]
                        except Exception:
                            pass
            except Exception as exc:
                err_json = json.dumps({"error": f"LLM streaming failed: {str(exc)}"})
                yield f"{err_json}\n"
                return

        duration = time.perf_counter() - start_time
        tps = round(output_tokens / duration, 1) if duration > 0 and output_tokens > 0 else 0.0

        if full_content:
            db_save_chat_message("assistant", full_content, full_thinking, model)

        db_record_request(
            endpoint="/api/chat",
            model=model,
            prompt_tokens=prompt_tokens or (len(str(messages)) // 4),
            completion_tokens=output_tokens or (len(full_content) // 4),
            latency_s=round(duration, 2),
            tps=tps,
            status_code=200
        )

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

# --- Universal LLM Proxy Endpoints (OpenAI-Compatible & Native) ---
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_backend(path: str, request: Request):
    full_path = request.url.path
    target_url = f"{LLM_BACKEND_URL}{full_path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in {"host", "content-length", "connection"}}

    body = await request.body()
    start_time = time.perf_counter()

    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            req = client.build_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body
            )
            response = await client.send(req, stream=True)

            async def proxy_stream():
                async for chunk in response.aiter_bytes():
                    yield chunk

            return StreamingResponse(
                proxy_stream(),
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except Exception as exc:
            return JSONResponse(status_code=502, content={"error": f"LLM backend gateway error: {str(exc)}"})

