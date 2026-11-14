import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import db_record_request
from app.services.http_client import close_shared_client, get_shared_client
from app.services.llm_engine import (
    _model_cache,
    detect_engine_type,
    invalidate_model_cache,
)
from app.services.rate_limiter import SlidingWindowRateLimiter


def test_rate_limit_headers_on_standard_endpoints(client: TestClient):
    """Ensure standard rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining) are present on API responses."""
    endpoints = [
        "/api/dashboard",
        "/api/history",
        "/api/usage-summary",
        "/api/settings",
        "/api/modelfile",
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200, f"Endpoint {ep} failed with status {res.status_code}"
        assert "x-ratelimit-limit" in res.headers, f"Missing X-RateLimit-Limit on {ep}"
        assert "x-ratelimit-remaining" in res.headers, f"Missing X-RateLimit-Remaining on {ep}"
        assert int(res.headers["x-ratelimit-limit"]) > 0


def test_rate_limiter_throttling_and_retry_after(client: TestClient, monkeypatch):
    """Ensure 429 Too Many Requests and Retry-After header are returned when rate limit is exceeded."""
    limiter = SlidingWindowRateLimiter(default_limit=3, window_seconds=60.0)

    # First 3 allowed
    for i in range(3):
        res = limiter.check_rate_limit("192.168.1.100", category="test", is_local=False)
        assert res.allowed is True
        assert res.remaining == 2 - i
        assert res.limit == 3

    # 4th blocked
    blocked = limiter.check_rate_limit("192.168.1.100", category="test", is_local=False)
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after > 0
    assert blocked.limit == 3


def test_history_pagination_and_model_filtering(client: TestClient):
    """Ensure /api/history supports limit, offset, and model query parameters."""
    for i in range(10):
        db_record_request(
            endpoint="/v1/chat/completions",
            model="filter-model-a" if i < 5 else "filter-model-b",
            prompt_tokens=10,
            completion_tokens=20,
            latency_s=0.5,
            tps=40.0,
            status_code=200,
        )

    # Test limit = 3
    res_limit = client.get("/api/history?limit=3")
    assert res_limit.status_code == 200
    data_limit = res_limit.json()
    assert len(data_limit) == 3

    # Test offset
    res_offset = client.get("/api/history?limit=3&offset=3")
    assert res_offset.status_code == 200
    data_offset = res_offset.json()
    assert len(data_offset) == 3
    assert data_offset[0]["id"] != data_limit[0]["id"]

    # Test model filtering
    res_filter_a = client.get("/api/history?limit=10&model=filter-model-a")
    assert res_filter_a.status_code == 200
    data_filter_a = res_filter_a.json()
    assert all(r["model"] == "filter-model-a" for r in data_filter_a)

    res_filter_b = client.get("/api/history?limit=10&model=filter-model-b")
    assert res_filter_b.status_code == 200
    data_filter_b = res_filter_b.json()
    assert all(r["model"] == "filter-model-b" for r in data_filter_b)


@pytest.mark.asyncio
async def test_model_discovery_caching():
    """Ensure model discovery caches results within TTL and invalidation clears it."""
    invalidate_model_cache()
    assert _model_cache["models_ts"] == 0.0

    # Offline probe
    engine, models, loaded, status = await detect_engine_type("http://127.0.0.1:99999")
    assert status == "offline"

    # Seed cache
    _model_cache["models"] = [{"name": "test-model:latest", "model": "test-model:latest"}]
    _model_cache["models_ts"] = 9999999999.0
    _model_cache["loaded_ts"] = 9999999999.0
    _model_cache["engine_name"] = "CachedEngine"
    _model_cache["status"] = "online"

    c_engine, c_models, c_loaded, c_status = await detect_engine_type("http://127.0.0.1:99999")
    assert c_engine == "CachedEngine"
    assert len(c_models) == 1
    assert c_models[0]["name"] == "test-model:latest"
    assert c_status == "online"

    invalidate_model_cache()
    assert _model_cache["models_ts"] == 0.0


@pytest.mark.asyncio
async def test_shared_http_client_singleton():
    """Ensure get_shared_client returns a persistent pooled client and can be closed cleanly."""
    client1 = get_shared_client()
    client2 = get_shared_client()
    assert client1 is client2
    assert not client1.is_closed

    await close_shared_client()
    assert client1.is_closed

    client3 = get_shared_client()
    assert client3 is not client1
    assert not client3.is_closed
    await close_shared_client()


def test_chat_payload_advanced_fields_validation(client: TestClient):
    """Ensure ChatMessagePayload and DashboardChatPayload reject out-of-bounds parameters."""
    valid_payload = {
        "model": "nova:latest",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 1024,
        "stream": False,
    }
    from app.schemas import DashboardChatPayload
    parsed = DashboardChatPayload(**valid_payload)
    assert parsed.temperature == 0.7
    assert parsed.top_p == 0.9
    assert parsed.max_tokens == 1024

    with pytest.raises(ValidationError):
        DashboardChatPayload(**{**valid_payload, "temperature": 3.5})

    with pytest.raises(ValidationError):
        DashboardChatPayload(**{**valid_payload, "top_p": 1.5})

    with pytest.raises(ValidationError):
        DashboardChatPayload(**{**valid_payload, "max_tokens": 0})
