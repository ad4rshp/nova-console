import json
import os
import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import (
    BASE_DIR,
    DEFAULT_MODEL,
    HOST,
    LLM_BACKEND_URL,
    NOVA_ALLOW_LAN,
    PORT,
    STATIC_DIR,
    is_loopback_host,
)
from app.database import (
    db_clear_chat_history,
    db_get_chat_history,
    db_get_recent_requests,
    db_get_settings,
    db_get_usage_summary,
    db_record_request,
    db_save_chat_message,
    db_set_setting,
    init_db,
)
from app.services.auth import (
    extract_token_from_request,
    get_or_create_admin_token,
    is_request_authenticated,
    verify_admin_token,
)
from app.services.llm_engine import get_dashboard_state
from app.services.modelfile import evict_model_vram, rebuild_nova_model, update_modelfile
from app.services.providers import get_provider
from app.services.rate_limiter import global_rate_limiter
from app.services.terminal import (
    generate_approval_token,
    run_system_command,
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
        f"http://[::1]:{PORT}",
        "http://127.0.0.1",
        "http://localhost",
        "http://[::1]",
    ]
    if NOVA_ALLOW_LAN and HOST not in ("127.0.0.1", "localhost", "::1"):
        origins.append(f"http://{HOST}:{PORT}")
    custom = os.environ.get("NOVA_CORS_ORIGINS", "")
    if custom:
        for c in custom.split(","):
            if c.strip():
                origins.append(c.strip())
    return origins

def is_valid_csrf_origin(origin_str: str) -> bool:
    if not origin_str:
        return False
    try:
        parsed = urlparse(origin_str)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port

        if scheme not in ("http", "https"):
            return False

        # Loopback origin validation: must match loopback IP/host and configured PORT
        if host in ("127.0.0.1", "localhost", "::1", "testserver"):
            if port is not None and port not in (PORT, 80, 443):
                custom_cors = os.environ.get("NOVA_CORS_ORIGINS", "")
                if not any(f":{port}" in c for c in custom_cors.split(",") if c.strip()):
                    return False
            return True

        # Check configured allowed origins (including LAN mode if active)
        allowed_list = get_allowed_origins()
        for allowed in allowed_list:
            p_allow = urlparse(allowed)
            if scheme == p_allow.scheme.lower() and host == (p_allow.hostname or "").lower():
                allow_port = p_allow.port
                if allow_port is None or port is None or allow_port == port:
                    return True

        return False
    except Exception:
        return False

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
        # 0. Request Correlation ID
        request_id = request.headers.get("X-Request-ID") or secrets.token_hex(8)
        request.state.request_id = request_id

        # 1. Request Body Size Limits (10MB global, 1MB for sensitive admin endpoints)
        is_sensitive = any(request.url.path.startswith(prefix) for prefix in SENSITIVE_API_PREFIXES)
        max_bytes = 1 * 1024 * 1024 if is_sensitive else 10 * 1024 * 1024
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    limit_mb = max_bytes // (1024 * 1024)
                    return JSONResponse(
                        status_code=413,
                        content={"error": f"Payload Too Large: request body exceeds maximum allowed limit of {limit_mb}MB."}
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid Content-Length header."})

        # 2. Authentication enforcement on sensitive routes when LAN mode is active or auth explicitly required
        require_auth = NOVA_ALLOW_LAN or os.environ.get("NOVA_REQUIRE_AUTH", "0") in ("1", "true", "yes")
        if is_sensitive and require_auth:
            if not is_request_authenticated(request):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Authentication required: LAN mode is active or sensitive administrative route accessed. Provide a valid Authorization Bearer or X-Nova-Auth token."}
                )

        # 3. Origin & CSRF Protection on state-changing API endpoints
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api/"):
            client_host = request.client.host if request.client else ""
            is_test_client = client_host in ("testclient", "testserver") or not client_host
            is_authed = is_request_authenticated(request)

            origin = request.headers.get("origin") or request.headers.get("referer")
            if not origin:
                if not is_test_client and not is_authed:
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Cross-Origin / CSRF security rejection: missing Origin or Referer header on state-changing request."}
                    )
            else:
                if not is_valid_csrf_origin(origin):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Cross-Origin / CSRF security rejection: unauthorized request origin (scheme, host, or port mismatch)."}
                    )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and run versioned migrations
    init_db()
    from app.database import db_checkpoint, db_cleanup_old_records
    db_checkpoint()
    try:
        db_cleanup_old_records()
    except Exception:
        pass
    yield
    db_checkpoint()

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
ALLOWED_SETTINGS = {"think", "save_chat_history", "preview_thinking", "theme", "auto_scroll"}

class SettingsPayload(BaseModel):
    think: bool | None = None
    save_chat_history: bool | None = None
    preview_thinking: str | None = Field(None, pattern=r"^(summary|full|hidden)$")
    theme: str | None = Field(None, pattern=r"^(light|dark|system)$")
    auto_scroll: bool | None = None

    model_config = ConfigDict(extra="forbid")

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
    if "settings" in state and isinstance(state["settings"], dict):
        state["settings"].pop("admin_auth_token", None)
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

@app.get("/api/settings")
async def get_settings_endpoint():
    settings = db_get_settings()
    settings.pop("admin_auth_token", None)
    return settings

@app.post("/api/settings")
async def update_settings(payload: SettingsPayload):
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        if k in ALLOWED_SETTINGS:
            db_set_setting(k, v)
    settings = db_get_settings()
    settings.pop("admin_auth_token", None)
    return settings

@app.post("/api/modelfile")
async def update_modelfile_endpoint(payload: ModelfilePayload):
    try:
        return update_modelfile(payload.model_dump(exclude_unset=True))
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

    provider = get_provider()

    async def stream_generator() -> AsyncGenerator[str, None]:
        start_time = time.perf_counter()
        full_content = ""
        full_thinking = ""
        prompt_tokens = 0
        output_tokens = 0
        token_source = "estimated"

        try:
            async for chunk in provider.chat(messages, model=model, stream=True, think=think):
                # Standard NDJSON line expected by dashboard.js
                yield json.dumps({
                    "message": {
                        "role": "assistant",
                        "content": chunk.get("content", ""),
                        "thinking": chunk.get("thinking", "")
                    },
                    "done": chunk.get("done", False)
                }) + "\n"

                if chunk.get("content"):
                    full_content += chunk["content"]
                if chunk.get("thinking"):
                    full_thinking += chunk["thinking"]
                if chunk.get("prompt_tokens") is not None:
                    prompt_tokens = chunk["prompt_tokens"]
                if chunk.get("completion_tokens") is not None:
                    output_tokens = chunk["completion_tokens"]
                if chunk.get("token_source") == "actual":
                    token_source = "actual"

        except Exception as exc:
            yield json.dumps({"error": f"{provider.name} streaming failed: {str(exc)}"}) + "\n"
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
            status_code=200,
            token_source=token_source
        )

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

# --- Universal OpenAI-Compatible API Proxy (/v1/) with Usage Tracking & Security ---
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_v1(path: str, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"

    # 1. Rate Limiting Enforcement
    allowed, remaining, retry_after = global_rate_limiter.check_rate_limit(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Too many requests."},
            headers={"Retry-After": str(int(retry_after))}
        )

    # 2. Proxy Authentication Enforcement (Mandatory when LAN mode or auth requirement is active)
    require_proxy_auth = NOVA_ALLOW_LAN or os.environ.get("NOVA_REQUIRE_AUTH", "0") in ("1", "true", "yes")
    if require_proxy_auth:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else request.headers.get("X-Nova-Auth", "")
        if not verify_admin_token(token):
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized: API proxy access requires valid Authorization Bearer token when LAN mode is active."}
            )

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

    client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))
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
            try:
                content = await response.aread()
                duration = time.perf_counter() - start_time
                status_code = response.status_code

                # Usage tracking for non-streaming completions
                if is_chat and status_code == 200:
                    prompt_tokens = 0
                    completion_tokens = 0
                    has_actual_tokens = False
                    try:
                        res_json = json.loads(content)
                        usage = res_json.get("usage", {})
                        if usage:
                            prompt_tokens = usage.get("prompt_tokens", 0)
                            completion_tokens = usage.get("completion_tokens", 0)
                            has_actual_tokens = True
                    except Exception:
                        pass

                    if not prompt_tokens and "messages" in req_json:
                        prompt_tokens = len(str(req_json["messages"])) // 4
                    if not completion_tokens:
                        completion_tokens = len(content) // 4

                    tps = round(completion_tokens / duration, 1) if duration > 0 and completion_tokens > 0 else 0.0
                    token_source = "actual" if has_actual_tokens else "estimated"
                    try:
                        db_record_request(
                            endpoint=f"/v1/{path}",
                            model=model_name,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            latency_s=round(duration, 2),
                            tps=tps,
                            status_code=status_code,
                            token_source=token_source
                        )
                    except Exception:
                        pass

                return Response(
                    content=content,
                    status_code=status_code,
                    headers=res_headers
                )
            finally:
                await response.aclose()
                await client.aclose()

        # Streaming response handling with leak-free lifecycle cleanup
        prompt_tokens_est = len(str(req_json.get("messages", ""))) // 4 if "messages" in req_json else 0

        async def streaming_wrapper():
            out_tokens = 0
            exact_prompt_tokens = prompt_tokens_est
            has_exact = False
            sse_buffer = ""
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
                    sse_buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in sse_buffer:
                        line, sse_buffer = sse_buffer.split("\n", 1)
                        line = line.strip()
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                cdata = json.loads(line[6:].strip())
                                if "usage" in cdata and cdata["usage"]:
                                    exact_prompt_tokens = cdata["usage"].get("prompt_tokens", exact_prompt_tokens)
                                    out_tokens = cdata["usage"].get("completion_tokens", out_tokens)
                                    has_exact = True
                                elif "choices" in cdata and cdata["choices"]:
                                    delta = cdata["choices"][0].get("delta", {})
                                    if delta.get("content"):
                                        out_tokens += max(1, len(delta["content"]) // 4)
                            except Exception:
                                pass

                # Process any trailing line in buffer
                if sse_buffer.strip().startswith("data: ") and sse_buffer.strip() != "data: [DONE]":
                    try:
                        cdata = json.loads(sse_buffer.strip()[6:].strip())
                        if "usage" in cdata and cdata["usage"]:
                            exact_prompt_tokens = cdata["usage"].get("prompt_tokens", exact_prompt_tokens)
                            out_tokens = cdata["usage"].get("completion_tokens", out_tokens)
                            has_exact = True
                    except Exception:
                        pass
            finally:
                # Guaranteed cleanup of upstream response and client on disconnect or completion
                await response.aclose()
                await client.aclose()
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
                            status_code=response.status_code,
                            token_source="actual" if has_exact else "estimated"
                        )
                    except Exception:
                        pass

        return StreamingResponse(
            streaming_wrapper(),
            status_code=response.status_code,
            headers=res_headers
        )

    except httpx.ConnectError:
        await client.aclose()
        is_authed = is_request_authenticated(request)
        error_detail = (
            f"Bad Gateway: Unable to connect to inference backend at {LLM_BACKEND_URL}. Ensure your engine is running."
            if is_authed else
            "Bad Gateway: Unable to connect to inference backend. Ensure the backend engine is running."
        )
        return JSONResponse(status_code=502, content={"error": error_detail})
    except Exception as exc:
        await client.aclose()
        is_authed = is_request_authenticated(request)
        error_detail = f"LLM backend gateway error: {str(exc)}" if is_authed else "LLM backend gateway error."
        return JSONResponse(status_code=502, content={"error": error_detail})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "An internal server error occurred. Internal details have been scrubbed for security."}
    )
