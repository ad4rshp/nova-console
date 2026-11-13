from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

class LLMProvider(ABC):
    """
    Abstract Base Class for LLM Inference Backends.
    Standardizes model management, streaming chat, and health checking across
    Ollama, LM Studio, vLLM, LocalAI, and other OpenAI-compatible servers.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    @property
    @abstractmethod
    def name(self) -> str:
        """Friendly provider name (e.g. 'Ollama', 'LM Studio', 'vLLM', 'LocalAI')."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Checks provider availability and returns status metadata."""
        pass

    @abstractmethod
    async def list_models(self) -> list[dict[str, Any]]:
        """Returns standard list of available models."""
        pass

    @abstractmethod
    async def list_loaded_models(self) -> list[dict[str, Any]]:
        """Returns models actively resident in memory/VRAM if supported."""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = True,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Yields standardized streaming chunks:
        {
            "content": str,
            "thinking": str,
            "done": bool,
            "prompt_tokens": int | None,
            "completion_tokens": int | None,
            "token_source": "actual" | "estimated"
        }
        """
        pass

    @abstractmethod
    async def unload_model(self, model: str) -> bool:
        """Evicts a model from VRAM/memory if supported by the provider."""
        pass

    async def get_model_info(self, model: str) -> dict[str, Any]:
        """Returns model details if supported."""
        return {"name": model}
