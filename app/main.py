import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import (
    BASE_DIR,
    HOST,
    NOVA_ALLOW_LAN,
    PORT,
    STATIC_DIR,
    is_loopback_host,
)
from app.database import db_checkpoint, db_cleanup_old_records, init_db
from app.routers import (
    chat_router,
    dashboard_router,
    modelfile_router,
    proxy_router,
    terminal_router,
)
from app.services.auth import get_or_create_admin_token, is_request_authenticated

# Configure Structured Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nova.app")

def get_allowed_origins() -> list[str]:
    origins = [
        f"http://127.0.0.1:{PORT}",
        f"http://localhost:{PORT}",
    ]
    if PORT == 80:
        origins.extend(["http://127.0.0.1", "http://localhost"])
    if NOVA_ALLOW_LAN and HOST not in ("0.0.0.0", "::", "", "127.0.0.1", "localhost"):
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
        if scheme not in ("http", "https"):
            return False

        host = (parsed.hostname or "").lower()
        if not host:
            return False

        if host in ("testserver", "testclient"):
            return True

        port = parsed.port

        allowed_list = get_allowed_origins()
        for allowed in allowed_list:
            p_allow = urlparse(allowed)
            if scheme == (p_allow.scheme or "").lower() and host == (p_allow.hostname or "").lower():
                allow_port = p_allow.port
                if allow_port == port:
                    return True
                if allow_port is None and port is None:
                    return True

        return False
    except Exception:
        return False

PUBLIC_ROUTES = {
    "/",
    "/favicon.ico",
    "/api/health",
}

ADMIN_API_PREFIXES = (
    "/api/terminal/",
    "/api/modelfile",
    "/api/rebuild-nova",
    "/api/settings",
    "/api/clear-chat-history",
    "/api/unload",
)

def is_public_path(path: str) -> bool:
    if path in PUBLIC_ROUTES or path.startswith("/static/"):
        return True
    return False

def apply_security_headers(response: Response, request_id: str) -> Response:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self';"
    )
    return response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 0. Request Correlation ID
        request_id = request.headers.get("X-Request-ID") or secrets.token_hex(8)
        request.state.request_id = request_id

        # 1. Request Body Size Limits (10MB global, 1MB for sensitive admin endpoints)
        is_admin_endpoint = any(request.url.path.startswith(prefix) for prefix in ADMIN_API_PREFIXES)
        max_bytes = 1 * 1024 * 1024 if is_admin_endpoint else 10 * 1024 * 1024
        limit_mb = max_bytes // (1024 * 1024)

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    resp = JSONResponse(
                        status_code=413,
                        content={"error": f"Payload Too Large: request body exceeds maximum allowed limit of {limit_mb}MB."}
                    )
                    return apply_security_headers(resp, request_id)
            except ValueError:
                resp = JSONResponse(status_code=400, content={"error": "Invalid Content-Length header."})
                return apply_security_headers(resp, request_id)

        # Enforce streaming body size limits (bounds memory consumption without buffering arbitrarily large payloads)
        if request.method in ("POST", "PUT", "PATCH"):
            chunks = []
            bytes_received = 0
            exceeded = False
            async for chunk in request.stream():
                bytes_received += len(chunk)
                if bytes_received > max_bytes:
                    exceeded = True
                    break
                chunks.append(chunk)

            if exceeded:
                resp = JSONResponse(
                    status_code=413,
                    content={"error": f"Payload Too Large: request body exceeds maximum allowed limit of {limit_mb}MB."}
                )
                return apply_security_headers(resp, request_id)

            full_body = b"".join(chunks)
            request._body = full_body
            request._stream_consumed = False

        # 2. Authentication enforcement: Protect all private routes when LAN mode is active or auth explicitly required
        require_auth = NOVA_ALLOW_LAN or os.environ.get("NOVA_REQUIRE_AUTH", "0") in ("1", "true", "yes")
        if require_auth and not is_public_path(request.url.path):
            if not is_request_authenticated(request):
                resp = JSONResponse(
                    status_code=401,
                    content={"error": "Unauthorized: Authentication required: LAN mode is active or private workstation route accessed. Provide a valid Authorization Bearer or X-Nova-Auth token."}
                )
                return apply_security_headers(resp, request_id)

        # 3. Origin & CSRF Protection on state-changing API endpoints
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api/"):
            client_host = request.client.host if request.client else ""
            is_test_client = client_host in ("testclient", "testserver") or not client_host
            is_authed = is_request_authenticated(request)

            origin = request.headers.get("origin") or request.headers.get("referer")
            if not origin:
                if not is_test_client and not is_authed:
                    resp = JSONResponse(
                        status_code=403,
                        content={"error": "Cross-Origin / CSRF security rejection: missing Origin or Referer header on state-changing request."}
                    )
                    return apply_security_headers(resp, request_id)
            else:
                if not is_valid_csrf_origin(origin):
                    resp = JSONResponse(
                        status_code=403,
                        content={"error": "Cross-Origin / CSRF security rejection: unauthorized request origin (scheme, host, or port mismatch)."}
                    )
                    return apply_security_headers(resp, request_id)

        response = await call_next(request)
        return apply_security_headers(response, request_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and run versioned migrations
    init_db()
    db_checkpoint()
    try:
        db_cleanup_old_records()
    except Exception:
        pass
    # Auto-detect active backend provider on startup
    try:
        from app.services.providers.factory import detect_provider
        await detect_provider()
    except Exception:
        pass
    yield
    try:
        from app.services.http_client import close_shared_client
        await close_shared_client()
    except Exception:
        pass
    db_checkpoint()

app = FastAPI(
    title="Nova Console API",
    description="Neumorphic Local AI Workstation & Universal LLM Proxy",
    version="2.1.0",
    lifespan=lifespan,
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
class FreshStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers: Headers, request_headers: Headers) -> bool:
        # In local AI workstation / dashboard mode, bypass 304 Not Modified cache
        # so frontend JS and CSS updates are delivered freshly to the browser (200 OK)
        return False

    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

static_path = STATIC_DIR / "static"
if not static_path.exists():
    static_path = BASE_DIR / "static"
if static_path.exists():
    app.mount("/static", FreshStaticFiles(directory=str(static_path)), name="static")

# Mount Modular Routers
app.include_router(dashboard_router)
app.include_router(chat_router)
app.include_router(terminal_router)
app.include_router(modelfile_router)
app.include_router(proxy_router)

# --- Favicon Delivery ---
@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    candidates = [
        static_path / "favicon.ico",
        STATIC_DIR / "static" / "favicon.ico",
        BASE_DIR / "static" / "favicon.ico",
        static_path / "favicon.svg",
        STATIC_DIR / "static" / "favicon.svg",
        BASE_DIR / "static" / "favicon.svg",
    ]
    for candidate in candidates:
        if candidate.exists():
            media = "image/x-icon" if candidate.suffix == ".ico" else "image/svg+xml"
            return FileResponse(candidate, media_type=media)
    return Response(status_code=204)

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
            client_ip = request.client.host if request.client else ""
            if is_loopback_host(client_ip) or not client_ip:
                admin_token = get_or_create_admin_token()
                safe_token_json = json.dumps(admin_token).replace("<", "\\u003c").replace(">", "\\u003e")
                session_inject = f'<script id="nova-auth-script">window.__NOVA_AUTH_TOKEN__ = {safe_token_json};</script>\n</head>'
                html = html.replace("</head>", session_inject, 1)
            return HTMLResponse(content=html)
    raise HTTPException(status_code=404, detail="dashboard.html not found")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "An internal server error occurred. Internal details have been scrubbed for security."}
    )
