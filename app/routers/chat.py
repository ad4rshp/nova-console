import json
import os
import sys
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import config
from app.config import DEFAULT_MODEL
from app.database import (
    db_clear_chat_history,
    db_get_chat_history,
    db_record_request,
    db_save_chat_message,
)
from app.schemas import DashboardChatPayload
from app.services.auth import is_request_authenticated
from app.services.providers import get_async_provider
from app.services.rate_limiter import global_rate_limiter

router = APIRouter(tags=["chat"])

def is_lan_mode_active() -> bool:
    app_main = sys.modules.get("app.main")
    if app_main and hasattr(app_main, "NOVA_ALLOW_LAN"):
        return bool(app_main.NOVA_ALLOW_LAN)
    return bool(getattr(config, "NOVA_ALLOW_LAN", False))

def enforce_chat_auth_if_required(request: Request) -> JSONResponse | None:
    require_auth = is_lan_mode_active() or os.environ.get("NOVA_REQUIRE_AUTH", "0") in ("1", "true", "yes")
    if require_auth and not is_request_authenticated(request):
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required: LAN mode is active or private conversation data accessed. Provide a valid Authorization Bearer or X-Nova-Auth token."}
        )
    return None

@router.get("/api/chat-history")
async def get_chat_history(request: Request):
    auth_err = enforce_chat_auth_if_required(request)
    if auth_err:
        return auth_err
    return db_get_chat_history()

@router.post("/api/clear-chat-history")
async def clear_chat_history(request: Request):
    auth_err = enforce_chat_auth_if_required(request)
    if auth_err:
        return auth_err
    db_clear_chat_history()
    return {"ok": True, "message": "Chat history cleared."}

@router.post("/api/dashboard-chat")
async def dashboard_chat(payload: DashboardChatPayload, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"

    # Enforce category-specific rate limit for chat generation (60 req/min default)
    allowed, remaining, retry_after = global_rate_limiter.check_rate_limit(client_ip, category="chat")
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded for chat generation. Please wait before sending more messages."},
            headers={"Retry-After": str(int(retry_after))},
        )

    model = payload.model or DEFAULT_MODEL
    messages_payload = payload.messages
    raw_prompt = payload.prompt
    images = payload.images or []

    # Construct messages list
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content, "images": m.images}
        for m in messages_payload
    ]

    if not messages and raw_prompt:
        messages = [{"role": "user", "content": raw_prompt}]

    # Validate image payloads
    valid_images = []
    for img in images:
        if isinstance(img, str) and (img.startswith("data:image/") or len(img) < 15 * 1024 * 1024):
            valid_images.append(img)

    if valid_images and messages and messages[-1].get("role") == "user":
        messages[-1]["images"] = valid_images

    think = bool(payload.think)

    if messages and messages[-1].get("role") == "user":
        db_save_chat_message("user", messages[-1].get("content", ""), "", model, images=valid_images)

    # Use asynchronous auto-detected provider
    provider = await get_async_provider()

    async def stream_generator() -> AsyncGenerator[str, None]:
        start_time = time.perf_counter()
        full_content = ""
        full_thinking = ""
        prompt_tokens = 0
        output_tokens = 0
        token_source = "estimated"

        try:
            async for chunk in provider.chat(messages, model=model, stream=True, think=think):
                yield json.dumps({
                    "message": {
                        "role": "assistant",
                        "content": chunk.get("content", ""),
                        "thinking": chunk.get("thinking", ""),
                    },
                    "done": chunk.get("done", False),
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
            token_source=token_source,
        )

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")
