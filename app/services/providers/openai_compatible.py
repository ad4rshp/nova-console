import json
from typing import Any, AsyncGenerator
import httpx
from app.services.providers.base import LLMProvider

class OpenAICompatibleAdapter(LLMProvider):
    """
    Adapter for OpenAI-compatible inference backends:
    LM Studio, vLLM, llama-server, LocalAI, and other /v1 implementations.
    """

    def __init__(self, base_url: str, provider_name: str = "OpenAI-Compatible Engine"):
        super().__init__(base_url)
        self._name = provider_name

    @property
    def name(self) -> str:
        return self._name

    async def health_check(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=2.5) as client:
            try:
                res = await client.get(f"{self.base_url}/v1/models")
                if res.status_code == 200:
                    return {"status": "online", "engine": self.name}
            except Exception:
                pass
        return {"status": "offline", "engine": self.name}

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=3.5) as client:
            try:
                res = await client.get(f"{self.base_url}/v1/models")
                if res.status_code == 200:
                    data = res.json()
                    raw = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    return [
                        {
                            "name": m.get("id") or m.get("name") or "unknown",
                            "model": m.get("id") or m.get("name") or "unknown",
                            "size": m.get("size", 0),
                            "details": m.get("details", {})
                        }
                        for m in raw
                    ]
            except Exception:
                pass
            return []

    async def list_loaded_models(self) -> list[dict[str, Any]]:
        # OpenAI API does not expose native loaded/vram offload stats; list all available
        return await self.list_models()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = True,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": kwargs.get("temperature", 0.7),
        }
        if "stream_options" not in payload and stream:
            payload["stream_options"] = {"include_usage": True}

        client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=8.0))
        full_content = ""
        try:
            async with client.stream("POST", f"{self.base_url}/v1/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    err_bytes = await response.aread()
                    yield {
                        "content": f"{self.name} error (HTTP {response.status_code}): {err_bytes.decode(errors='replace')}",
                        "thinking": "",
                        "done": True,
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "token_source": "incomplete"
                    }
                    return

                actual_prompt_tokens = None
                actual_completion_tokens = None

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            cdata = json.loads(data_str)
                        except Exception:
                            continue

                        # Extract provider-reported usage if available
                        if "usage" in cdata and cdata["usage"]:
                            u = cdata["usage"]
                            actual_prompt_tokens = u.get("prompt_tokens")
                            actual_completion_tokens = u.get("completion_tokens")

                        content = ""
                        thinking = ""
                        choices = cdata.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            thinking = delta.get("thinking", "") or delta.get("reasoning_content", "")
                            if content:
                                full_content += content

                        yield {
                            "content": content,
                            "thinking": thinking,
                            "done": False,
                            "prompt_tokens": actual_prompt_tokens,
                            "completion_tokens": actual_completion_tokens,
                            "token_source": "actual" if (actual_completion_tokens is not None) else "estimated"
                        }

                # Final completion marker
                token_source = "actual" if actual_completion_tokens is not None else "estimated"
                yield {
                    "content": "",
                    "thinking": "",
                    "done": True,
                    "prompt_tokens": actual_prompt_tokens or (len(str(messages)) // 4),
                    "completion_tokens": actual_completion_tokens or (len(full_content) // 4),
                    "token_source": token_source
                }
        finally:
            await client.aclose()

    async def unload_model(self, model: str) -> bool:
        # Standard OpenAI API does not define a model unload endpoint
        return False

class LMStudioAdapter(OpenAICompatibleAdapter):
    def __init__(self, base_url: str):
        super().__init__(base_url, provider_name="LM Studio")

class VLLMAdapter(OpenAICompatibleAdapter):
    def __init__(self, base_url: str):
        super().__init__(base_url, provider_name="vLLM")

class LocalAIAdapter(OpenAICompatibleAdapter):
    def __init__(self, base_url: str):
        super().__init__(base_url, provider_name="LocalAI")
