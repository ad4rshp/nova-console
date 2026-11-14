import time

import pytest

from app.config import HOST, NOVA_ALLOW_LAN, WORKSPACE_DIR
from app.services.terminal import (
    assess_command_risk,
    generate_approval_token,
    is_safe_workspace_path,
    run_system_command,
    validate_working_dir,
    verify_and_consume_token,
)


def test_default_network_binding_localhost():
    """Ensure the application defaults strictly to 127.0.0.1 loopback, never 0.0.0.0 without opt-in."""
    assert HOST == "127.0.0.1"
    assert not NOVA_ALLOW_LAN

def test_terminal_execute_unauthorized_without_token(client):
    """Ensure unauthenticated/tokenless command execution is rejected with 403."""
    res = client.post("/api/terminal/execute", json={
        "command": "dir",
        "approved": True
    })
    assert res.status_code == 422 or res.status_code == 403

def test_token_issuance_and_consumption():
    """Ensure tokens are issued cryptographically, bound to command, and consumed on single use."""
    cmd = "echo 'testing security'"
    token_data = generate_approval_token(cmd)
    token = token_data["approval_token"]
    assert token
    assert token_data["command"] == cmd
    assert token_data["risk"] == "LOW"

    # First verification must succeed
    valid, msg, record = verify_and_consume_token(token, cmd)
    assert valid is True
    assert record is not None

    # Replay attempt must be rejected (single-use token)
    valid_replay, replay_msg, _ = verify_and_consume_token(token, cmd)
    assert valid_replay is False
    assert "replay" in replay_msg.lower() or "invalid" in replay_msg.lower()

def test_token_command_tampering_rejected():
    """Ensure a token issued for command A cannot be used to execute command B."""
    token_data = generate_approval_token("git status")
    token = token_data["approval_token"]

    valid, msg, _ = verify_and_consume_token(token, "rm -rf .")
    assert valid is False
    assert "tampering" in msg.lower() or "mismatch" in msg.lower()

def test_token_expiration():
    """Ensure expired tokens are rejected."""
    token_data = generate_approval_token("echo expire_test")
    token = token_data["approval_token"]

    from app.services.terminal import _APPROVAL_TOKENS
    # Artificially expire the token
    _APPROVAL_TOKENS[token]["expires_at"] = time.time() - 5.0

    valid, msg, _ = verify_and_consume_token(token, "echo expire_test")
    assert valid is False
    assert "expired" in msg.lower()

def test_working_dir_path_traversal_confinement():
    """Ensure working directory cannot escape WORKSPACE_DIR into sensitive system paths."""
    base = WORKSPACE_DIR.resolve()

    # Traversal attempt outside workspace
    outside_path = base.parent.parent
    validated = validate_working_dir(str(outside_path))
    assert validated == base

    # None or empty returns base
    assert validate_working_dir(None) == base

def test_catastrophic_command_blocked():
    """Ensure dangerous catastrophic operations are identified as blocked."""
    assessment = assess_command_risk("rm -rf /")
    assert assessment["risk"] == "CRITICAL"
    assert assessment["blocked"] is True

    assessment_fmt = assess_command_risk("format c:")
    assert assessment_fmt["risk"] == "CRITICAL"
    assert assessment_fmt["blocked"] is True

def test_security_headers_present(client):
    """Ensure security headers are present in HTTP responses."""
    res = client.get("/")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

def test_csrf_origin_rejection(client):
    """Ensure cross-origin state-changing POST requests from untrusted web domains are rejected with 403."""
    res = client.post(
        "/api/clear-chat-history",
        headers={"Origin": "https://malicious-website.com"}
    )
    assert res.status_code == 403
    assert "CSRF" in res.json().get("error", "")

def test_api_command_token_replay_rejected(client):
    """API level test: Replay attack with an already-consumed approval token must be rejected."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    # 1. Propose command
    propose_res = client.post("/api/terminal/propose", json={"command": "echo replay_test"})
    assert propose_res.status_code == 200
    token = propose_res.json()["approval_token"]

    # 2. First execution succeeds
    exec_res = client.post("/api/terminal/execute", json={
        "command": "echo replay_test",
        "approval_token": token,
        "user_authorization": admin_token,
        "approved": True
    })
    assert exec_res.status_code == 200
    assert exec_res.json()["ok"] is True

    # 3. Second execution with identical token MUST fail
    replay_res = client.post("/api/terminal/execute", json={
        "command": "echo replay_test",
        "approval_token": token,
        "user_authorization": admin_token,
        "approved": True
    })
    assert replay_res.status_code == 403
    assert "replay" in replay_res.json()["error"].lower() or "invalid" in replay_res.json()["error"].lower()

def test_api_command_tampering_rejected(client):
    """API level test: Modifying command or working directory after token issuance must be rejected."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    propose_res = client.post("/api/terminal/propose", json={"command": "echo original"})
    token = propose_res.json()["approval_token"]

    # Tampering: submit different command with original token
    tampered_res = client.post("/api/terminal/execute", json={
        "command": "echo modified_attack",
        "approval_token": token,
        "user_authorization": admin_token,
        "approved": True
    })
    assert tampered_res.status_code == 403
    assert "tampering" in tampered_res.json()["error"].lower()

def test_path_traversal_confinement_deep():
    """Ensure various path traversal attempts are strictly confined to WORKSPACE_DIR."""
    base = WORKSPACE_DIR.resolve()
    traversal_payloads = [
        "../../",
        "..\\..\\",
        "../../../../Windows/System32",
        "../../../../etc/passwd",
        "/etc/shadow",
        "C:\\Windows\\System32",
        "~",
        "./../../",
    ]
    for payload in traversal_payloads:
        resolved = validate_working_dir(payload)
        assert resolved == base or resolved.is_relative_to(base), f"Traversal escaped on payload: {payload}"

def test_host_binding_bypasses():
    """Ensure all non-loopback bind hosts require NOVA_ALLOW_LAN=1, preventing bypasses."""
    from app.config import is_loopback_host, validate_bind_host

    # Non-loopback addresses that MUST raise ValueError when allow_lan=False
    blocked_hosts = [
        "0.0.0.0",
        "::",
        "[::]",
        "192.168.1.100",
        "10.0.0.1",
        "172.16.0.5",
        "8.8.8.8",
        "attacker.local",
        "malicious.domain.com"
    ]
    for host in blocked_hosts:
        with pytest.raises(ValueError) as excinfo:
            validate_bind_host(host, allow_lan=False)
        assert "requires NOVA_ALLOW_LAN=1" in str(excinfo.value), f"Host bypass allowed: {host}"

    # When allow_lan=True, binding is permitted
    assert validate_bind_host("0.0.0.0", allow_lan=True) == "0.0.0.0"
    assert validate_bind_host("192.168.1.50", allow_lan=True) == "192.168.1.50"

    # Loopback hosts must succeed even when allow_lan=False
    assert is_loopback_host("127.0.0.1") is True
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("::1") is True
    assert validate_bind_host("127.0.0.1", allow_lan=False) == "127.0.0.1"
    assert validate_bind_host("localhost", allow_lan=False) == "localhost"

def test_cross_platform_command_execution():
    """Ensure safe commands execute cross-platform, secrets are scrubbed, and unauth calls are rejected."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    # 1. Unauthenticated execution fails with 401
    token_data = generate_approval_token("echo auth_test")
    unauth_result = run_system_command("echo auth_test", approval_token=token_data["approval_token"], user_authorization="invalid_token")
    assert unauth_result["ok"] is False
    assert unauth_result["return_code"] == 401

    # 2. Authenticated execution succeeds
    token_data2 = generate_approval_token("echo cross_platform_test")
    auth_result = run_system_command("echo cross_platform_test", approval_token=token_data2["approval_token"], user_authorization=admin_token)
    assert auth_result["ok"] is True
    assert auth_result["return_code"] == 0
    assert "cross_platform_test" in auth_result["output"]

    # 3. Secret scrubbing in output
    token_data3 = generate_approval_token("echo Bearer sk-supersecretkey1234567890")
    scrub_result = run_system_command("echo Bearer sk-supersecretkey1234567890", approval_token=token_data3["approval_token"], user_authorization=admin_token)
    assert scrub_result["ok"] is True
    assert "[REDACTED]" in scrub_result["output"]
    assert "sk-supersecretkey1234567890" not in scrub_result["output"]

def test_lan_mode_sensitive_routes_require_authentication(client, monkeypatch):
    """Ensure that when LAN mode is active (NOVA_ALLOW_LAN=True), all sensitive routes require auth."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    monkeypatch.setattr("app.main.NOVA_ALLOW_LAN", True)

    sensitive_endpoints = [
        ("GET", "/api/dashboard", None),
        ("GET", "/api/history", None),
        ("GET", "/api/usage-summary", None),
        ("GET", "/api/settings", None),
        ("POST", "/api/dashboard-chat", {"model": "nova:latest", "messages": [{"role": "user", "content": "hello"}]}),
        ("POST", "/api/terminal/propose", {"command": "echo test"}),
        ("POST", "/api/settings", {"theme": "dark"}),
        ("POST", "/api/clear-chat-history", {}),
        ("POST", "/api/unload", {"model": "nova:latest"}),
    ]

    for method, path, payload in sensitive_endpoints:
        # Without auth: must return 401 Unauthorized
        req_kwargs = {"json": payload} if payload is not None else {}
        res_no_auth = client.request(method, path, **req_kwargs)
        assert res_no_auth.status_code == 401, f"Expected 401 for {path} without auth in LAN mode, got {res_no_auth.status_code}"
        assert "Authentication required" in res_no_auth.json().get("error", "")

        # With valid X-Nova-Auth header: should NOT return 401
        res_with_auth = client.request(method, path, **req_kwargs, headers={"X-Nova-Auth": admin_token})
        assert res_with_auth.status_code != 401, f"Expected non-401 for {path} with valid auth header"

def test_terminal_lan_auto_disable(monkeypatch):
    """Ensure terminal execution is disabled by default on LAN-exposed instances."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    # Simulate LAN mode enabled, but terminal LAN opt-in NOT enabled
    monkeypatch.setattr("app.config.NOVA_ALLOW_LAN", True)
    monkeypatch.delenv("NOVA_ENABLE_TERMINAL_LAN", raising=False)

    token_data = generate_approval_token("echo lan_test")
    res = run_system_command("echo lan_test", approval_token=token_data["approval_token"], user_authorization=admin_token)
    assert res["ok"] is False
    assert res["return_code"] == 403
    assert "disabled by default on network-exposed" in res["error"]

    # When explicitly opted in via NOVA_ENABLE_TERMINAL_LAN=1, execution proceeds
    monkeypatch.setenv("NOVA_ENABLE_TERMINAL_LAN", "1")
    token_data2 = generate_approval_token("echo lan_test_opted_in")
    res2 = run_system_command("echo lan_test_opted_in", approval_token=token_data2["approval_token"], user_authorization=admin_token)
    assert res2["ok"] is True

def test_terminal_command_allowlist(monkeypatch):
    """Ensure configurable command allowlists block non-approved binaries."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    # Configure strict allowlist permitting only 'python' and 'echo'
    monkeypatch.setenv("NOVA_STRICT_ALLOWLIST", "1")
    monkeypatch.setenv("NOVA_COMMAND_ALLOWLIST", "python,echo")

    # 1. Allowed command succeeds
    t_allowed = generate_approval_token("echo allowed_command")
    res_allowed = run_system_command("echo allowed_command", approval_token=t_allowed["approval_token"], user_authorization=admin_token)
    assert res_allowed["ok"] is True

    # 2. Non-allowlisted command is blocked with 403
    t_blocked = generate_approval_token("whoami")
    res_blocked = run_system_command("whoami", approval_token=t_blocked["approval_token"], user_authorization=admin_token)
    assert res_blocked["ok"] is False
    assert res_blocked["return_code"] == 403
    assert "not in the approved command allowlist" in res_blocked["error"]

def test_backend_url_ssrf_protection(monkeypatch):
    """Ensure SSRF attacks, cloud metadata endpoints, embedded credentials, and DNS rebinding are blocked."""
    from app.config import validate_backend_url

    # Prohibited schemes
    with pytest.raises(ValueError) as exc:
        validate_backend_url("file:///etc/passwd")
    assert "scheme must be http or https" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate_backend_url("ftp://internal-server.local")
    assert "scheme must be http or https" in str(exc.value)

    # Cloud metadata endpoints
    with pytest.raises(ValueError) as exc:
        validate_backend_url("http://169.254.169.254/latest/meta-data/")
    assert "strictly prohibited" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate_backend_url("http://metadata.google.internal")
    assert "strictly prohibited" in str(exc.value)

    # Embedded credentials in URL
    with pytest.raises(ValueError) as exc:
        validate_backend_url("http://admin:secret123@127.0.0.1:11434")
    assert "Embedded credentials" in str(exc.value)

    # DNS rebinding to metadata service
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("169.254.169.254", 80))])
    with pytest.raises(ValueError) as exc:
        validate_backend_url("http://attacker-rebinding.com:11434")
    assert "metadata" in str(exc.value).lower()

    # Valid backends succeed
    monkeypatch.undo()
    assert validate_backend_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert validate_backend_url("http://localhost:1234") == "http://localhost:1234"
    assert validate_backend_url("https://api.openai.com/v1") == "https://api.openai.com/v1"

def test_token_in_query_string_ignored(client, monkeypatch):
    """Ensure ?token= query parameter is ignored and does NOT authorize sensitive routes."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    monkeypatch.setattr("app.main.NOVA_ALLOW_LAN", True)

    # Passing token in query string should return 401 Unauthorized
    res = client.post(f"/api/settings?token={admin_token}", json={"theme": "dark"})
    assert res.status_code == 401

    # Passing token in header must succeed
    res_hdr = client.post("/api/settings", json={"theme": "dark"}, headers={"X-Nova-Auth": admin_token})
    assert res_hdr.status_code == 200

def test_admin_token_not_leaked_in_settings(client):
    """Ensure admin_auth_token is scrubbed and never exposed in settings or dashboard responses."""
    # 1. GET /api/settings
    res = client.get("/api/settings")
    assert res.status_code == 200
    assert "admin_auth_token" not in res.json()

    # 2. POST /api/settings
    res_post = client.post("/api/settings", json={"theme": "light"})
    assert res_post.status_code == 200
    assert "admin_auth_token" not in res_post.json()

    # 3. GET /api/dashboard
    res_dash = client.get("/api/dashboard")
    assert res_dash.status_code == 200
    dash_settings = res_dash.json().get("settings", {})
    assert "admin_auth_token" not in dash_settings

def test_request_size_limits(client):
    """Ensure oversized request bodies are rejected with 413 Payload Too Large."""
    # Exceeding 1MB on /api/settings
    res_settings = client.post(
        "/api/settings",
        content="x" * 100,
        headers={"Content-Length": str(2 * 1024 * 1024), "Content-Type": "application/json"}
    )
    assert res_settings.status_code == 413
    assert "Payload Too Large" in res_settings.json().get("error", "")

    # Exceeding 10MB on /v1/models
    res_proxy = client.post(
        "/v1/models",
        content="x" * 100,
        headers={"Content-Length": str(15 * 1024 * 1024), "Content-Type": "application/json"}
    )
    assert res_proxy.status_code == 413

def test_terminal_sandbox_strict_chaining_blocked(monkeypatch):
    """Ensure shell chaining operators are rejected in strict sandbox mode."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    monkeypatch.setenv("NOVA_TERMINAL_SANDBOX", "strict")

    chaining_payloads = [
        "echo safe; cat /etc/passwd",
        "echo a && echo b",
        "echo a || echo b",
        "echo a | grep a",
        "echo `whoami`",
        "echo $(whoami)",
    ]

    for payload in chaining_payloads:
        token_data = generate_approval_token(payload)
        res = run_system_command(payload, approval_token=token_data["approval_token"], user_authorization=admin_token)
        assert res["ok"] is False
        assert res["return_code"] == 403
        assert "forbidden" in res["error"].lower() or "blocked" in res["error"].lower()

def test_terminal_concurrency_limit():
    """Ensure concurrent terminal executions beyond the semaphore capacity return 429."""
    from app.services.auth import get_or_create_admin_token
    from app.services.terminal import _TERMINAL_SEMAPHORE
    admin_token = get_or_create_admin_token()

    # Artificially exhaust semaphore
    for _ in range(3):
        assert _TERMINAL_SEMAPHORE.acquire(blocking=False) is True

    try:
        t_data = generate_approval_token("echo concurrency_test")
        res = run_system_command("echo concurrency_test", approval_token=t_data["approval_token"], user_authorization=admin_token)
        assert res["ok"] is False
        assert res["return_code"] == 429
        assert "concurrency limit" in res["error"].lower()
    finally:
        # Release acquired slots
        for _ in range(3):
            _TERMINAL_SEMAPHORE.release()

def test_csrf_deep_validation(client):
    """Ensure CSRF validation checks scheme, host, and port."""
    from app.config import PORT

    # 1. Invalid port on localhost
    res_bad_port = client.post(
        "/api/clear-chat-history",
        headers={"Origin": f"http://127.0.0.1:{PORT + 1111}"}
    )
    assert res_bad_port.status_code == 403

    # 2. Invalid scheme
    res_bad_scheme = client.post(
        "/api/clear-chat-history",
        headers={"Origin": f"ftp://127.0.0.1:{PORT}"}
    )
    assert res_bad_scheme.status_code == 403

    # 3. Valid loopback and port
    res_valid = client.post(
        "/api/clear-chat-history",
        headers={"Origin": f"http://127.0.0.1:{PORT}"}
    )
    assert res_valid.status_code == 200

def test_lan_mode_rejects_untrusted_origins(client, monkeypatch):
    """Ensure that in LAN mode, arbitrary non-loopback website origins (e.g. evil.com) are rejected."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    monkeypatch.setattr("app.main.NOVA_ALLOW_LAN", True)

    untrusted_origins = [
        "https://evil.com",
        "http://attacker.org:8080",
        "https://malicious-site.io",
        "http://192.168.1.99:9999",
    ]

    for bad_origin in untrusted_origins:
        res = client.post(
            "/api/settings",
            json={"theme": "dark"},
            headers={"Origin": bad_origin, "X-Nova-Auth": admin_token}
        )
        assert res.status_code == 403, f"Expected 403 for untrusted LAN origin {bad_origin}, got {res.status_code}"
        assert "CSRF" in res.json().get("error", "")

def test_chat_history_requires_auth_in_lan_mode(client, monkeypatch):
    """Ensure chat history retrieval and clearing require authentication when LAN mode is active."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    monkeypatch.setattr("app.main.NOVA_ALLOW_LAN", True)

    # 1. Unauthenticated GET /api/chat-history must return 401
    get_unauth = client.get("/api/chat-history")
    assert get_unauth.status_code == 401

    # 2. Authenticated GET /api/chat-history succeeds
    get_auth = client.get("/api/chat-history", headers={"X-Nova-Auth": admin_token})
    assert get_auth.status_code == 200

    # 3. Unauthenticated POST /api/clear-chat-history must return 401
    clear_unauth = client.post("/api/clear-chat-history")
    assert clear_unauth.status_code == 401

    # 4. Authenticated POST /api/clear-chat-history succeeds
    clear_auth = client.post("/api/clear-chat-history", headers={"X-Nova-Auth": admin_token})
    assert clear_auth.status_code == 200

def test_chat_payload_validation_rejects_malformed_inputs(client):
    """Ensure dashboard chat endpoint strictly validates roles, message counts, and lengths."""
    # 1. Invalid role
    res_bad_role = client.post("/api/dashboard-chat", json={
        "messages": [{"role": "hacker", "content": "malicious input"}]
    })
    assert res_bad_role.status_code == 422

    # 2. Invalid model pattern
    res_bad_model = client.post("/api/dashboard-chat", json={
        "model": "model; rm -rf /",
        "messages": [{"role": "user", "content": "hello"}]
    })
    assert res_bad_model.status_code == 422

    # 3. Excessive messages (>100)
    huge_messages = [{"role": "user", "content": f"msg {i}"} for i in range(105)]
    res_excessive = client.post("/api/dashboard-chat", json={
        "messages": huge_messages
    })
    assert res_excessive.status_code == 422

def test_terminal_global_disable_flag(monkeypatch):
    """Ensure setting NOVA_DISABLE_TERMINAL=1 blocks all command execution."""
    from app.services.auth import get_or_create_admin_token
    from app.services.terminal import generate_approval_token, run_system_command
    admin_token = get_or_create_admin_token()

    monkeypatch.setenv("NOVA_DISABLE_TERMINAL", "1")

    token_data = generate_approval_token("echo test_disabled")
    res = run_system_command("echo test_disabled", approval_token=token_data["approval_token"], user_authorization=admin_token)
    assert res["ok"] is False
    assert res["return_code"] == 403
    assert "disabled" in res["error"].lower()

def test_rate_limiter_bounded_storage_and_categories():
    """Ensure SlidingWindowRateLimiter limits by category and prunes old keys to prevent unbounded memory."""
    from app.services.rate_limiter import SlidingWindowRateLimiter
    limiter = SlidingWindowRateLimiter(default_limit=10, max_tracked_keys=50)

    # Category limits
    allowed_chat, rem_chat, _ = limiter.check_rate_limit("1.2.3.4", category="chat")
    assert allowed_chat is True
    assert rem_chat > 0

    allowed_proxy, rem_proxy, _ = limiter.check_rate_limit("1.2.3.4", category="proxy")
    assert allowed_proxy is True

    # Memory bounding: add 100 distinct client IPs
    for i in range(100):
        limiter.check_rate_limit(f"10.0.0.{i}", category="chat")

    # Storage should be bounded to around max_tracked_keys
    assert len(limiter._requests) <= 55

def test_csp_header_present(client):
    """Ensure Content-Security-Policy header is present on HTTP responses."""
    res = client.get("/")
    assert res.status_code == 200
    assert "Content-Security-Policy" in res.headers
    assert "default-src 'self'" in res.headers["Content-Security-Policy"]

def test_frontend_xss_payload_handling_in_history(client):
    """Ensure malicious model names or paths in request history are recorded as text without injection."""
    from app.database import db_record_request

    xss_payload = "<script>alert('xss')</script>"
    db_record_request("/v1/chat/completions", xss_payload, 10, 20, 0.5, 40.0)

    res = client.get("/api/history")
    assert res.status_code == 200
    data = res.json()
    assert any(r["model"] == xss_payload for r in data)

def test_terminal_container_requirement_policy(monkeypatch, client):
    """Ensure requiring container isolation fails closed with HTTP 503 when Docker is unavailable."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    monkeypatch.setenv("NOVA_REQUIRE_CONTAINER", "1")
    monkeypatch.setattr("app.services.terminal.is_docker_available", lambda: False)

    token_data = generate_approval_token("python --version")
    res = run_system_command("python --version", approval_token=token_data["approval_token"], user_authorization=admin_token)

    assert res["ok"] is False
    assert res["return_code"] == 503
    assert "container isolation is required by policy" in res["error"].lower()
    assert res["isolation_mode"] == "container_docker_required_failed"

    # Also verify the API endpoint returns 503 Service Unavailable
    token_data2 = generate_approval_token("python --version")
    api_res = client.post("/api/terminal/execute", json={
        "command": "python --version",
        "approval_token": token_data2["approval_token"],
        "user_authorization": admin_token,
        "approved": True
    })
    assert api_res.status_code == 503
    assert api_res.json()["return_code"] == 503

def test_terminal_windows_job_object_setup():
    """Ensure Windows Job Objects can be created and configured with resource caps on Windows."""
    import platform
    import subprocess

    from app.services.terminal import _setup_windows_job_object

    if platform.system() != "Windows":
        pytest.skip("Windows Job Objects test only applies to Windows systems")

    proc = subprocess.Popen(["cmd.exe", "/c", "echo job_test"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    job = _setup_windows_job_object(int(proc._handle), memory_limit_mb=512, max_processes=16)
    out, _ = proc.communicate()
    assert job is not None
    assert int(job) != 0

    import ctypes
    ctypes.windll.kernel32.CloseHandle(job)
    assert b"job_test" in out

def test_terminal_isolation_mode_metadata():
    """Ensure terminal execution returns transparent isolation_mode and security_notice."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    token_data = generate_approval_token("echo isolation_test")
    res = run_system_command("echo isolation_test", approval_token=token_data["approval_token"], user_authorization=admin_token)

    assert res["ok"] is True
    assert "isolation_mode" in res
    assert res["isolation_mode"] == "host_subprocess_restricted"
    assert "security_notice" in res
    assert "application OS-user permissions" in res["security_notice"]

def test_terminal_deep_injection_and_traversal(monkeypatch):
    """Ensure command injection chaining and path traversal attempts are detected and blocked."""
    from app.services.auth import get_or_create_admin_token
    admin_token = get_or_create_admin_token()

    # 1. Path traversal detection via is_safe_workspace_path
    assert is_safe_workspace_path(str(WORKSPACE_DIR)) is True
    assert is_safe_workspace_path(str(WORKSPACE_DIR / "subfolder")) is True
    assert is_safe_workspace_path("../../") is False
    assert is_safe_workspace_path(r"..\..\Windows\System32") is False
    assert is_safe_workspace_path("/etc/passwd") is False

    # 2. Command injection chaining blocked in strict allowlist mode
    monkeypatch.setenv("NOVA_STRICT_ALLOWLIST", "1")
    injection_payloads = [
        "python --version && calc.exe",
        "echo safe; rm -rf /",
        "dir | findstr secret",
        "echo a & calc.exe",
        "python -c 'print(1)' > out.txt",
        "echo test \n whoami",
    ]
    for payload in injection_payloads:
        t_data = generate_approval_token(payload)
        res = run_system_command(payload, approval_token=t_data["approval_token"], user_authorization=admin_token)
        assert res["ok"] is False, f"Chaining payload was not blocked: {payload}"
        assert res["return_code"] == 403
        assert "forbidden" in res["error"].lower() or "not in the approved command allowlist" in res["error"].lower()

def test_proxy_path_traversal_blocked(client):
    """Ensure upstream API proxy blocks directory traversal in paths."""
    res = client.get("/v1/models/..%2fsecret")
    assert res.status_code == 400
    assert "Invalid upstream proxy path" in res.json().get("error", "")





