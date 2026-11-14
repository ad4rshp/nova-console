import asyncio

import pytest

from app.services.resource_manager import (
    ResourceManager,
    ResourceOverloadError,
    ResourceTimeoutError,
    global_resource_manager,
)


def test_hardware_profile_structure_and_fault_tolerance():
    """Ensure get_hardware_profile returns expected sections without raising exceptions."""
    profile = global_resource_manager.get_hardware_profile()
    assert isinstance(profile, dict)
    assert "cpu" in profile
    assert "ram" in profile
    assert "gpu" in profile
    assert "storage" in profile
    assert "concurrency" in profile

    cpu = profile["cpu"]
    assert "cores" in cpu and cpu["cores"] > 0
    assert "name" in cpu

    ram = profile["ram"]
    assert "total_gb" in ram
    assert "used_gb" in ram
    assert "percent" in ram

    concurrency = profile["concurrency"]
    assert "max_concurrent_generations" in concurrency
    assert "max_queued_generations" in concurrency
    assert "current_queued" in concurrency


def test_kv_cache_estimation():
    """Verify KV-cache memory requirement calculations with different context sizes and models."""
    assert ResourceManager.estimate_kv_cache_mb(0) == 0.0
    assert ResourceManager.estimate_kv_cache_mb(-100) == 0.0

    kv_2k = ResourceManager.estimate_kv_cache_mb(2048, model_size_b=7.0)
    assert kv_2k == 256.0

    kv_4k = ResourceManager.estimate_kv_cache_mb(4096, model_size_b=7.0)
    assert kv_4k == 512.0

    kv_8k = ResourceManager.estimate_kv_cache_mb(8192, model_size_b=7.0)
    assert kv_8k == 1024.0

    kv_70b = ResourceManager.estimate_kv_cache_mb(4096, model_size_b=70.0)
    assert kv_70b > kv_4k


def test_model_fit_evaluation():
    """Verify adaptive model fit recommendations against host memory and VRAM."""
    mgr = ResourceManager()
    fit = mgr.evaluate_model_fit(model_size_mb=4000.0, context_length=2048)

    assert isinstance(fit, dict)
    assert fit["model_size_mb"] == 4000.0
    assert fit["estimated_kv_cache_mb"] == 256.0
    assert fit["total_estimated_mb"] == 4256.0
    assert "fits_in_vram" in fit
    assert "fits_in_ram" in fit
    assert "recommended_context" in fit
    assert fit["recommended_context"] in (2048, 4096, 8192)
    assert isinstance(fit["warnings"], list)


@pytest.mark.asyncio
async def test_generation_concurrency_queue_and_overload(monkeypatch):
    """Verify that generation concurrency limits and queue capacity are strictly enforced."""
    monkeypatch.setenv("NOVA_MAX_CONCURRENT_GENERATIONS", "1")
    monkeypatch.setenv("NOVA_MAX_QUEUED_GENERATIONS", "2")
    monkeypatch.setenv("NOVA_QUEUE_TIMEOUT_SECONDS", "0.2")

    mgr = ResourceManager()
    assert mgr.max_concurrent == 1
    assert mgr.max_queued == 2
    assert mgr.queue_timeout == 0.2

    # Slot 1: Active generation
    await mgr.acquire_generation_slot()

    # Slot 2 & 3: Fill queue
    async def queue_slot():
        return await mgr.acquire_generation_slot()

    task1 = asyncio.create_task(queue_slot())
    task2 = asyncio.create_task(queue_slot())
    await asyncio.sleep(0.01)

    # Next attempt should be rejected with ResourceOverloadError (Queue Full -> HTTP 429)
    with pytest.raises(ResourceOverloadError):
        await mgr.acquire_generation_slot()

    # Wait for the queued tasks to time out
    with pytest.raises(ResourceTimeoutError):
        await task1
    with pytest.raises(ResourceTimeoutError):
        await task2

    # Release initial slot
    mgr.release_generation_slot()

    # Slot can now be acquired cleanly
    await mgr.acquire_generation_slot()
    mgr.release_generation_slot()
