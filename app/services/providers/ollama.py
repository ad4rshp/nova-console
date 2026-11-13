import json
from typing import Any, AsyncGenerator
import httpx
from app.services.providers.base import LLMProvider

class OllamaAdapter(LLMProvider):
    """Adapter for Ollama native API (/api/*)."""

    @property
    def name(self) -> str:
        return "Ollama"

    async def health_check(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=2.5) as client:
            try:
                res = await client.get(f"{self.base_url}/api/version")
                if res.status_code == 200:
                    ver = res.json().get("version", "unknown")
                    return {"status": "online", "version": ver, "engine": "Ollama"}
            except Exception:
                pass
            try:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    return {"status": "online", "version": "active", "engine": "Ollama"}
            except Exception:
                pass
        return {"status": "offline", "engine": "Ollama"}

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{self.base_url}/api/tags")
            if res.status_code == 200:
                raw = res.json().get("models", [])
                return [
                    {
                        "name": m.get("name") or m.get("model"),
                        "model": m.get("name") or m.get("model"),
                        "size": m.get("size", 0),
                        "details": m.get("details", {})
                    }
                    for m in raw
                ]
            return []

    async def list_loaded_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                res = await client.get(f"{self.base_url}/api/ps")
                if res.status_code == 200:
                    return res.json().get("models", [])
            except Exception:
                pass
            return []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = True,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        req_body = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "think": kwargs.get("think", False)
        }
        client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=8.0))
        try:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=req_body) as response:
                if response.status_code != 200:
                    err_bytes = await response.aread()
                    yield {
                        "content": f"Ollama error (HTTP {response.status_code}): {err_bytes.decode(errors='replace')}",
                        "thinking": "",
                        "done": True,
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "token_source": "incomplete"
                    }
                    return

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue

                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    thinking = msg.get("thinking", "")
                    done = bool(data.get("done", False))

                    prompt_tokens = data.get("prompt_eval_count")
                    completion_tokens = data.get("eval_count")
                    token_source = "actual" if (prompt_tokens is not None or completion_tokens is not None) else "incomplete"

                    yield {
                        "content": content,
                        "thinking": thinking,
                        "done": done,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "token_source": token_source
                    }
        finally:
            await client.aclose()

    async def unload_model(self, model: str) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model, "keep_alive": 0}
                )
                return res.status_code == 200
            except Exception:
                return False

    async def get_model_info(self, model: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                res = await client.post(f"{self.base_url}/api/show", json={"name": model})
                if res.status_code == 200:
                    return res.json()
            except Exception:
                pass
        return {"name": model}
