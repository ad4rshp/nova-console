import json
import os
import sys
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app import config
from app.config import LLM_BACKEND_URL
from app.database import db_record_request
from app.services.auth import is_request_authenticated, verify_admin_token
from app.services.rate_limiter import global_rate_limiter

router = APIRouter(tags=["proxy"])

def is_lan_mode_active() -> bool:
    app_main = sys.modules.get("app.main")
    if app_main and hasattr(app_main, "NOVA_ALLOW_LAN"):
        return bool(app_main.NOVA_ALLOW_LAN)
    return bool(getattr(config, "NOVA_ALLOW_LAN", False))

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
    "content-length",
}

@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_v1(path: str, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"

    # 1. Rate Limiting Enforcement (Category: proxy, 120 req/min default)
    allowed, remaining, retry_after = global_rate_limiter.check_rate_limit(client_ip, category="proxy")
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Too many requests."},
            headers={"Retry-After": str(int(retry_after))},
        )

    # 2. Proxy Authentication Enforcement (Mandatory when LAN mode or auth requirement is active)
    require_proxy_auth = is_lan_mode_active() or os.environ.get("NOVA_REQUIRE_AUTH", "0") in ("1", "true", "yes")
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else request.headers.get("X-Nova-Auth", "")
    
    if require_proxy_auth:
        if not verify_admin_token(token):
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized: API proxy access requires valid Authorization Bearer token when LAN mode is active."},
            )

    # Path traversal defense: block any attempted directory traversal in proxy URL
    if ".." in path or path.startswith(("/", "\\")):
        return JSONResponse(
            status_code=400,
            content={"error": "Bad Request: Invalid upstream proxy path."}
        )

    target_url = f"{LLM_BACKEND_URL}/v1/{path}"

    # 3. Secure Upstream Header Forwarding
    # Explicitly strip hop-by-hop headers, cookies, and internal Nova credentials so they never leak to upstream LLMs
    backend_api_key = os.environ.get("NOVA_BACKEND_API_KEY") or os.environ.get("BACKEND_API_KEY")
    headers: dict[str, str] = {}
    
    for k, v in request.headers.items():
        k_lower = k.lower()
        if k_lower in HOP_BY_HOP_HEADERS:
            continue
        if k_lower in ("x-nova-auth", "x-nova-admin", "x-nova-key", "cookie", "set-cookie"):
            continue
        if k_lower == "authorization":
            # If the client sent Nova's admin token, strip it so it does not leak upstream
            prov_tok = v[7:].strip() if v.startswith("Bearer ") else v.strip()
            if verify_admin_token(prov_tok):
                continue
        headers[k] = v

    # Attach configured upstream backend API key if present and authorization not already set
    if backend_api_key and "authorization" not in {k.lower() for k in headers}:
        headers["Authorization"] = f"Bearer {backend_api_key.strip()}"

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
            content=body,
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
                            token_source=token_source,
                        )
                    except Exception:
                        pass

                return Response(
                    content=content,
                    status_code=status_code,
                    headers=res_headers,
                )
            finally:
                await response.aclose()
                await client.aclose()

        # Streaming response handling with incremental SSE event buffer
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
                            token_source="actual" if has_exact else "estimated",
                        )
                    except Exception:
                        pass

        return StreamingResponse(
            streaming_wrapper(),
            status_code=response.status_code,
            headers=res_headers,
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
