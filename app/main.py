import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import (
    STATIC_DIR,
    BASE_DIR,
    LLM_BACKEND_URL,
    DEFAULT_MODEL,
    PORT,
    HOST,
    NOVA_ALLOW_LAN,
    is_loopback_host,
)
from app.services.auth import (
    get_or_create_admin_token,
    verify_admin_token,
    extract_token_from_request,
    is_request_authenticated,
)
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
from app.services.terminal import (
    assess_command_risk,
    generate_approval_token,
    run_system_command,
    validate_working_dir,
)
from app.services.updater import check_for_updates

# Hop-by-hop headers to strip during HTTP proxying
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length"
}

def get_allowed_origins() -> list[str]:
    origins = [
        f"http://127.0.0.1:{PORT}",
        f"http://localhost:{PORT}",
        "http://127.0.0.1",
        "http://localhost",
    ]
    custom = os.environ.get("NOVA_CORS_ORIGINS", "")
    if custom:
        for c in custom.split(","):
            if c.strip():
                origins.append(c.strip())
    return origins

SENSITIVE_API_PREFIXES = (
    "/api/terminal/",
    "/api/modelfile",
    "/api/rebuild-nova",
    "/api/settings",
    "/api/clear-chat-history",
    "/api/unload",
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Authentication enforcement on sensitive routes when LAN mode is active or auth explicitly required
        is_sensitive = any(request.url.path.startswith(prefix) for prefix in SENSITIVE_API_PREFIXES)
        require_auth = NOVA_ALLOW_LAN or os.environ.get("NOVA_REQUIRE_AUTH", "0") in ("1", "true", "yes")

        if is_sensitive and require_auth:
            if not is_request_authenticated(request):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Authentication required: LAN mode is active or sensitive administrative route accessed. Provide a valid Authorization Bearer or X-Nova-Auth token."}
                )

        # 2. Origin & CSRF Protection on state-changing API endpoints
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                parsed = urlparse(origin)
                origin_host = parsed.hostname or ""
                # Reject external/cross-origin requests attempting to manipulate local state
                if origin_host not in ("127.0.0.1", "localhost", "::1", "testserver") and not NOVA_ALLOW_LAN:
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Cross-Origin / CSRF security rejection: unauthorized request origin."}
                    )

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and run versioned migrations
    init_db()
    yield

app = FastAPI(
    title="Nova Console API",
    description="Neumorphic Local AI Workstation & Universal LLM Proxy",
    version="2.1.0",
    lifespan=lifespan
)

# Strict CORS: Only local loopback origins (unless configured via NOVA_CORS_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

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
    model: str = Field(..., max_length=128)

class ProposeCommandPayload(BaseModel):
    command: str = Field(..., max_length=4096)
    working_dir: str | None = None

class ExecuteCommandPayload(BaseModel):
    command: str = Field(..., max_length=4096)
    working_dir: str | None = None
    approval_token: str = Field(..., min_length=16, max_length=128)
    user_authorization: str | None = None
    approved: bool | None = None

# --- Frontend HTML Delivery ---
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    candidates = [
        BASE_DIR / "app" / "templates" / "dashboard.html",
        STATIC_DIR / "app" / "templates" / "dashboard.html",
        STATIC_DIR / "templates" / "dashboard.html",
        STATIC_DIR / "dashboard.html",
        BASE_DIR / "dashboard.html",
    ]
    for candidate in candidates:
        if candidate.exists():
            html = candidate.read_text(encoding="utf-8")
            # For loopback sessions, inject the local session auth token into window context
            client_ip = request.client.host if request.client else ""
            if is_loopback_host(client_ip) or not client_ip:
                admin_token = get_or_create_admin_token()
                session_inject = f'<script id="nova-auth-script">window.__NOVA_AUTH_TOKEN__ = "{admin_token}";</script>\n</head>'
                html = html.replace("</head>", session_inject, 1)
            return HTMLResponse(content=html)
    raise HTTPException(status_code=404, detail="dashboard.html not found")

# --- Core Dashboard API ---
@app.get("/api/dashboard")
async def get_dashboard(request: Request):
    state = await get_dashboard_state()
    state["auth"] = {
        "lan_mode": NOVA_ALLOW_LAN,
        "is_authenticated": is_request_authenticated(request)
    }
    return state

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

# --- Terminal Command Execution Endpoints with Cryptographic Token Authorization ---
@app.post("/api/terminal/propose")
async def propose_terminal_command(payload: ProposeCommandPayload):
    token_data = generate_approval_token(payload.command, working_dir=payload.working_dir)
    return token_data

@app.post("/api/terminal/execute")
async def execute_terminal_command(payload: ExecuteCommandPayload, request: Request):
    if not payload.approval_token:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "Execution declined: cryptographic server approval token required."}
        )

    # Extract and verify server-side user authorization
    user_auth = payload.user_authorization or extract_token_from_request(request)
    if not verify_admin_token(user_auth):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Execution declined: valid server-side user authorization credential required."}
        )

    result = run_system_command(
        payload.command,
        working_dir=payload.working_dir,
        approval_token=payload.approval_token,
        user_authorization=user_auth
    )
    if not result.get("ok"):
        code = result.get("return_code", 403)
        status_code = code if code in (401, 403) else 400
        return JSONResponse(status_code=status_code, content=result)
    return result

# --- Streaming Chat with Local Engine ---
@app.post("/api/dashboard-chat")
async def dashboard_chat(request: Request):
    payload = await request.json()
    model = payload.get("model", DEFAULT_MODEL)
    messages = payload.get("messages", [])
    images = payload.get("images", [])
    if not messages and "prompt" in payload:
        messages = [{"role": "user", "content": payload["prompt"]}]

    # Validate image payloads
    valid_images = []
    for img in images:
        if isinstance(img, str) and (img.startswith("data:image/") or len(img) < 15 * 1024 * 1024):
            valid_images.append(img)

    if valid_images and messages and messages[-1].get("role") == "user":
        messages[-1]["images"] = valid_images

    think = bool(payload.get("think", False))

    if messages and messages[-1].get("role") == "user":
        db_save_chat_message("user", messages[-1].get("content", ""), "", model, images=valid_images)

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

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=8.0)) as client:
            try:
                chat_url = f"{LLM_BACKEND_URL}/api/chat"
                async with client.stream("POST", chat_url, json=ollama_req) as response:
                    if response.status_code != 200:
                        body_err = await response.aread()
                        err_text = body_err.decode(errors="replace")
                        try:
                            err_parsed = json.loads(err_text).get("error", err_text)
                        except Exception:
                            err_parsed = err_text
                        yield json.dumps({"error": f"Inference Engine (HTTP {response.status_code}): {err_parsed}"}) + "\n"
                        return

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
            except httpx.ConnectError:
                err_msg = f"Cannot connect to Ollama at {LLM_BACKEND_URL}. Ensure Ollama is running ('ollama serve') or select an active model."
                yield json.dumps({"error": err_msg}) + "\n"
                return
            except httpx.ConnectTimeout:
                err_msg = f"Connection timed out reaching {LLM_BACKEND_URL}. Check if your inference engine is frozen or starting up."
                yield json.dumps({"error": err_msg}) + "\n"
                return
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

# --- Universal OpenAI-Compatible API Proxy (/v1/) with Usage Tracking ---
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_v1(path: str, request: Request):
    target_url = f"{LLM_BACKEND_URL}/v1/{path}"
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }

    body = await request.body()
    start_time = time.perf_counter()

    is_chat = path.startswith("chat/completions") or path.startswith("completions")
    req_json: dict[str, Any] = {}
    if is_chat and body:
        try:
            req_json = json.loads(body)
        except Exception:
            pass

    model_name = req_json.get("model", "default")
    is_stream = bool(req_json.get("stream", False))

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        try:
            req = client.build_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body
            )
            response = await client.send(req, stream=is_stream)

            res_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in HOP_BY_HOP_HEADERS
            }

            if not is_stream:
                content = await response.aread()
                duration = time.perf_counter() - start_time
                status_code = response.status_code

                # Usage tracking for non-streaming completions
                if is_chat and status_code == 200:
                    prompt_tokens = 0
                    completion_tokens = 0
                    try:
                        res_json = json.loads(content)
                        usage = res_json.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)
                    except Exception:
                        pass

                    if not prompt_tokens and "messages" in req_json:
                        prompt_tokens = len(str(req_json["messages"])) // 4
                    if not completion_tokens:
                        completion_tokens = len(content) // 4

                    tps = round(completion_tokens / duration, 1) if duration > 0 and completion_tokens > 0 else 0.0
                    try:
                        db_record_request(
                            endpoint=f"/v1/{path}",
                            model=model_name,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            latency_s=round(duration, 2),
                            tps=tps,
                            status_code=status_code
                        )
                    except Exception:
                        pass

                return Response(
                    content=content,
                    status_code=status_code,
                    headers=res_headers
                )

            # Streaming response handling
            prompt_tokens_est = len(str(req_json.get("messages", ""))) // 4 if "messages" in req_json else 0

            async def streaming_wrapper():
                out_tokens = 0
                exact_prompt_tokens = prompt_tokens_est
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                        chunk_str = chunk.decode("utf-8", errors="ignore")
                        for line in chunk_str.split("\n"):
                            line = line.strip()
                            if line.startswith("data: ") and line != "data: [DONE]":
                                try:
                                    cdata = json.loads(line[6:])
                                    if "usage" in cdata and cdata["usage"]:
                                        exact_prompt_tokens = cdata["usage"].get("prompt_tokens", exact_prompt_tokens)
                                        out_tokens = cdata["usage"].get("completion_tokens", out_tokens)
                                    elif "choices" in cdata and cdata["choices"]:
                                        delta = cdata["choices"][0].get("delta", {})
                                        if delta.get("content"):
                                            out_tokens += max(1, len(delta["content"]) // 4)
                                except Exception:
                                    pass
                finally:
                    await response.aclose()
                    duration = time.perf_counter() - start_time
                    tps = round(out_tokens / duration, 1) if duration > 0 and out_tokens > 0 else 0.0
                    if is_chat:
                        try:
                            db_record_request(
                                endpoint=f"/v1/{path}",
                                model=model_name,
                                prompt_tokens=exact_prompt_tokens,
                                completion_tokens=out_tokens,
                                latency_s=round(duration, 2),
                                tps=tps,
                                status_code=response.status_code
                            )
                        except Exception:
                            pass

            return StreamingResponse(
                streaming_wrapper(),
                status_code=response.status_code,
                headers=res_headers
            )

        except httpx.ConnectError:
            return JSONResponse(
                status_code=502,
                content={"error": f"Bad Gateway: Unable to connect to inference backend at {LLM_BACKEND_URL}. Ensure your engine is running."}
            )
        except Exception as exc:
            return JSONResponse(status_code=502, content={"error": f"LLM backend gateway error: {str(exc)}"})
