
def test_dashboard_api_endpoint(client):
    """Ensure /api/dashboard returns structured state without crashing."""
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "ram" in data
    assert "gpu" in data
    assert "models" in data

def test_terminal_propose_and_execute_flow(client):
    """Ensure proposing generates a token, user auth is strictly verified, and replay is prevented."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    propose_res = client.post("/api/terminal/propose", json={"command": "python --version"})
    assert propose_res.status_code == 200
    pdata = propose_res.json()
    token = pdata.get("approval_token")
    assert token

    # 1. Executing without user authorization must be rejected with 401
    unauth_res = client.post("/api/terminal/execute", json={
        "command": "python --version",
        "approval_token": token,
        "approved": True
    })
    assert unauth_res.status_code == 401
    assert "user authorization" in unauth_res.json().get("error", "").lower()

    # 2. Execute with valid token AND valid user authorization
    exec_res = client.post("/api/terminal/execute", json={
        "command": "python --version",
        "approval_token": token,
        "user_authorization": admin_token,
        "approved": True
    })
    assert exec_res.status_code == 200
    edata = exec_res.json()
    assert edata["ok"] is True
    assert edata["return_code"] == 0

    # 3. Replaying the consumed token must be rejected with 403
    replay_res = client.post("/api/terminal/execute", json={
        "command": "python --version",
        "approval_token": token,
        "user_authorization": admin_token,
        "approved": True
    })
    assert replay_res.status_code == 403

def test_modelfile_bounds_validation(client):
    """Ensure parameter bounds are enforced and reject out-of-range values."""
    # num_ctx limit is (1024, 65536)
    bad_res = client.post("/api/modelfile", json={"num_ctx": 9999999})
    assert bad_res.status_code == 400
    assert "outside safe limits" in bad_res.json()["error"]

    # Valid values should succeed
    good_res = client.post("/api/modelfile", json={"num_ctx": 4096, "temperature": 0.4})
    assert good_res.status_code == 200
    assert good_res.json()["parameters"]["num_ctx"] == "4096"

def test_settings_strict_validation(client):
    """Ensure settings endpoint enforces strict schema, rejecting unknown keys and invalid values."""
    # 1. Unknown / injected setting keys must be rejected with 422
    bad_key_res = client.post("/api/settings", json={"unsupported_key": "malicious_value"})
    assert bad_key_res.status_code == 422

    # 2. Invalid enum values (e.g. unknown theme or preview_thinking) must be rejected with 422
    bad_theme_res = client.post("/api/settings", json={"theme": "neon_green_injected"})
    assert bad_theme_res.status_code == 422

    # 3. Valid settings must succeed
    good_res = client.post("/api/settings", json={
        "theme": "dark",
        "think": True,
        "preview_thinking": "summary"
    })
    assert good_res.status_code == 200
    data = good_res.json()
    assert data["theme"] == "dark"
    assert data["think"] is True

def test_proxy_authentication_in_lan_mode(client, monkeypatch):
    """Ensure /v1/ proxy requires Bearer token authentication when LAN mode is active."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    monkeypatch.setattr("app.main.NOVA_ALLOW_LAN", True)

    # 1. Unauthenticated request to /v1/ must return 401
    unauth_res = client.get("/v1/models")
    assert unauth_res.status_code == 401
    assert "Unauthorized" in unauth_res.json().get("error", "")

    # 2. Authenticated request with Bearer token is accepted through to backend
    auth_res = client.get("/v1/models", headers={"Authorization": f"Bearer {admin_token}"})
    # Status code will either be 200 or 502 (if local backend is offline in test runner), but crucially NOT 401
    assert auth_res.status_code != 401

def test_proxy_rate_limiting(client, monkeypatch):
    """Ensure proxy enforces rate limits and returns 429 when thresholds are exceeded."""
    from app.services.rate_limiter import global_rate_limiter
    global_rate_limiter.reset()

    # Artificially set low rate limit threshold
    monkeypatch.setenv("NOVA_RATE_LIMIT_PER_MINUTE", "3")

    # Send 3 allowed requests
    for _ in range(3):
        res = client.get("/v1/models")
        assert res.status_code != 429

    # 4th request must be rate limited with 429
    blocked_res = client.get("/v1/models")
    assert blocked_res.status_code == 429
    assert "Rate limit exceeded" in blocked_res.json().get("error", "")
    assert "Retry-After" in blocked_res.headers

    # Reset limiter for subsequent tests
    global_rate_limiter.reset()

def test_request_correlation_id_header(client):
    """Ensure X-Request-ID correlation header is assigned and returned on responses."""
    # 1. Without client request ID, server generates one
    res1 = client.get("/api/dashboard")
    assert res1.status_code == 200
    assert "X-Request-ID" in res1.headers
    assert len(res1.headers["X-Request-ID"]) >= 8

    # 2. Client-provided request ID is preserved
    custom_id = "test-corr-id-12345"
    res2 = client.get("/api/dashboard", headers={"X-Request-ID": custom_id})
    assert res2.headers.get("X-Request-ID") == custom_id



