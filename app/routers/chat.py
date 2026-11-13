import json
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import DEFAULT_MODEL
from app.database import (
    db_clear_chat_history,
    db_get_chat_history,
    db_record_request,
    db_save_chat_message,
)
from app.services.providers import get_provider

router = APIRouter(tags=["chat"])

@router.get("/api/chat-history")
async def get_chat_history():
    return db_get_chat_history()

@router.post("/api/clear-chat-history")
async def clear_chat_history():
    db_clear_chat_history()
    return {"ok": True, "message": "Chat history cleared."}

@router.post("/api/dashboard-chat")
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
