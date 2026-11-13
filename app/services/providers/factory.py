import os

import httpx

from app.config import LLM_BACKEND_URL
from app.services.providers.base import LLMProvider
from app.services.providers.ollama import OllamaAdapter
from app.services.providers.openai_compatible import (
    LlamaServerAdapter,
    LMStudioAdapter,
    LocalAIAdapter,
    OpenAICompatibleAdapter,
    VLLMAdapter,
)

_CACHED_PROVIDER: LLMProvider | None = None

def create_provider_by_type(provider_type: str, url: str) -> LLMProvider:
    p_lower = provider_type.strip().lower()
    if p_lower == "ollama":
        return OllamaAdapter(url)
    elif p_lower in ("lmstudio", "lm_studio", "lm-studio"):
        return LMStudioAdapter(url)
    elif p_lower in ("vllm", "v-llm"):
        return VLLMAdapter(url)
    elif p_lower in ("localai", "local_ai", "local-ai"):
        return LocalAIAdapter(url)
    elif p_lower in ("llama", "llama.cpp", "llama-server", "llamacpp"):
        return LlamaServerAdapter(url)
    else:
        return OpenAICompatibleAdapter(url)

async def detect_provider(url: str = LLM_BACKEND_URL) -> LLMProvider:
    """
    Auto-detects the running provider by probing server endpoints and response headers.
    Avoids brittle port heuristics whenever the backend is reachable.
    """
    global _CACHED_PROVIDER

    explicit_type = os.environ.get("NOVA_PROVIDER_TYPE", "").strip()
    if explicit_type:
        _CACHED_PROVIDER = create_provider_by_type(explicit_type, url)
        return _CACHED_PROVIDER

    async with httpx.AsyncClient(timeout=2.0) as client:
        # 1. Probe Ollama (/api/tags)
        try:
            res = await client.get(f"{url}/api/tags")
            if res.status_code == 200 and "models" in res.json():
                _CACHED_PROVIDER = OllamaAdapter(url)
                return _CACHED_PROVIDER
        except Exception:
            pass

        # 2. Probe llama.cpp / llama-server (/health)
        try:
            res = await client.get(f"{url}/health")
            if res.status_code == 200:
                body = res.text.lower()
                if "slots" in body or "llama" in body or "idle" in body:
                    _CACHED_PROVIDER = LlamaServerAdapter(url)
                    return _CACHED_PROVIDER
        except Exception:
            pass

        # 3. Probe OpenAI-compatible /v1/models (inspecting Server header and payload)
        try:
            res = await client.get(f"{url}/v1/models")
            if res.status_code == 200:
                server_hdr = res.headers.get("server", "").lower()
                headers_str = str(res.headers).lower()

                if "llama" in server_hdr or "llama.cpp" in headers_str:
                    _CACHED_PROVIDER = LlamaServerAdapter(url)
                elif "lmstudio" in server_hdr or "lmstudio" in headers_str:
                    _CACHED_PROVIDER = LMStudioAdapter(url)
                elif "vllm" in server_hdr or "vllm" in headers_str:
                    _CACHED_PROVIDER = VLLMAdapter(url)
                elif "localai" in server_hdr or "localai" in headers_str:
                    _CACHED_PROVIDER = LocalAIAdapter(url)
                else:
                    _CACHED_PROVIDER = OpenAICompatibleAdapter(url)
                return _CACHED_PROVIDER
        except Exception:
            pass

    # Port-based heuristics fallback only when offline / probing fails
    if ":11434" in url:
        _CACHED_PROVIDER = OllamaAdapter(url)
    elif ":1234" in url:
        _CACHED_PROVIDER = LMStudioAdapter(url)
    elif ":8000" in url:
        _CACHED_PROVIDER = VLLMAdapter(url)
    elif ":8081" in url or "llama" in url:
        _CACHED_PROVIDER = LlamaServerAdapter(url)
    elif "localai" in url:
        _CACHED_PROVIDER = LocalAIAdapter(url)
    else:
        _CACHED_PROVIDER = OllamaAdapter(url)

    return _CACHED_PROVIDER

async def get_async_provider(url: str = LLM_BACKEND_URL, force_refresh: bool = False) -> LLMProvider:
    """
    Returns the auto-detected provider asynchronously.
    """
    global _CACHED_PROVIDER
    if _CACHED_PROVIDER and not force_refresh:
        return _CACHED_PROVIDER
    return await detect_provider(url)

def get_provider(url: str = LLM_BACKEND_URL) -> LLMProvider:
    """
    Returns current or cached provider adapter synchronously.
    """
    global _CACHED_PROVIDER
    if _CACHED_PROVIDER:
        return _CACHED_PROVIDER

    explicit_type = os.environ.get("NOVA_PROVIDER_TYPE", "").strip()
    if explicit_type:
        _CACHED_PROVIDER = create_provider_by_type(explicit_type, url)
        return _CACHED_PROVIDER

    if ":1234" in url:
        _CACHED_PROVIDER = LMStudioAdapter(url)
    elif ":8000" in url:
        _CACHED_PROVIDER = VLLMAdapter(url)
    elif ":8081" in url or "llama" in url:
        _CACHED_PROVIDER = LlamaServerAdapter(url)
    elif "localai" in url:
        _CACHED_PROVIDER = LocalAIAdapter(url)
    else:
        _CACHED_PROVIDER = OllamaAdapter(url)

    return _CACHED_PROVIDER
