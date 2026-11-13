import time
import pytest
from app.services.hardware import get_ram_stats, get_gpu_stats, get_storage_stats

def test_ram_stats_structure():
    """Ensure RAM statistics return valid measured fields without fabricating."""
    ram = get_ram_stats()
    assert "total_gb" in ram
    assert "used_gb" in ram
    assert "percent" in ram
    assert "status" in ram
    if ram["status"] == "active":
        assert ram["total_gb"] > 0
        assert 0 <= ram["percent"] <= 100

def test_gpu_stats_structure():
    """Ensure GPU detection returns valid hardware type and status."""
    gpu = get_gpu_stats()
    assert "type" in gpu
    assert "name" in gpu
    assert "status" in gpu
    assert gpu["type"] in ("nvidia", "apple_metal", "amd_rocm", "cpu_only", "unknown")

def test_storage_stats_caching():
    """Ensure storage queries run quickly and utilize in-memory TTL caching."""
    t0 = time.perf_counter()
    s1 = get_storage_stats()
    d1 = time.perf_counter() - t0

    t1 = time.perf_counter()
    s2 = get_storage_stats()
    d2 = time.perf_counter() - t1

    assert "disk_free_gb" in s1
    assert "model_dir_gb" in s1
    # Second call should be instant (from cache)
    assert d2 < 0.05
    assert s1["model_dir_gb"] == s2["model_dir_gb"]

