import pytest

from app.services.providers import (
    LlamaServerAdapter,
    LLMProvider,
    LMStudioAdapter,
    LocalAIAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
    VLLMAdapter,
    create_provider_by_type,
)


def test_provider_adapter_instantiation():
    """Ensure all provider adapters instantiate correctly with standard interfaces."""
    ollama = OllamaAdapter("http://127.0.0.1:11434")
    assert ollama.name == "Ollama"
    assert isinstance(ollama, LLMProvider)
    assert ollama.capabilities["vram_eviction"] is True
    assert ollama.capabilities["modelfile_compilation"] is True

    lmstudio = LMStudioAdapter("http://127.0.0.1:1234")
    assert lmstudio.name == "LM Studio"
    assert isinstance(lmstudio, OpenAICompatibleAdapter)

    vllm = VLLMAdapter("http://127.0.0.1:8000")
    assert vllm.name == "vLLM"
    assert isinstance(vllm, OpenAICompatibleAdapter)

    localai = LocalAIAdapter("http://127.0.0.1:8080")
    assert localai.name == "LocalAI"
    assert isinstance(localai, OpenAICompatibleAdapter)

    llama = LlamaServerAdapter("http://127.0.0.1:8080")
    assert "llama" in llama.name.lower()
    assert llama.capabilities["slots_monitoring"] is True

def test_provider_factory():
    """Ensure provider factory creates correct adapter by type string."""
    p1 = create_provider_by_type("ollama", "http://127.0.0.1:11434")
    assert isinstance(p1, OllamaAdapter)

    p2 = create_provider_by_type("lmstudio", "http://127.0.0.1:1234")
    assert isinstance(p2, LMStudioAdapter)

    p3 = create_provider_by_type("vllm", "http://127.0.0.1:8000")
    assert isinstance(p3, VLLMAdapter)

    p4 = create_provider_by_type("localai", "http://127.0.0.1:8080")
    assert isinstance(p4, LocalAIAdapter)

    p5 = create_provider_by_type("llama.cpp", "http://127.0.0.1:8080")
    assert isinstance(p5, LlamaServerAdapter)

@pytest.mark.asyncio
async def test_provider_offline_health_check():
    """Ensure health check returns clean status even when endpoint is unreachable."""
    provider = OllamaAdapter("http://127.0.0.1:99999")
    status = await provider.health_check()
    assert status["status"] == "offline"
    assert status["engine"] == "Ollama"
