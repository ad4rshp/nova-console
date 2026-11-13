import os
import time
import pytest
from app.config import HOST, NOVA_ALLOW_LAN, WORKSPACE_DIR
from app.services.terminal import (
    generate_approval_token,
    verify_and_consume_token,
    validate_working_dir,
    assess_command_risk,
    run_system_command,
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
    from app.config import validate_bind_host, is_loopback_host

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
        ("POST", "/api/terminal/propose", {"command": "echo test"}),
        ("POST", "/api/settings", {"theme": "dark"}),
        ("POST", "/api/clear-chat-history", {}),
        ("POST", "/api/unload", {"model": "nova:latest"}),
    ]

    for method, path, payload in sensitive_endpoints:
        # Without auth: must return 401 Unauthorized
        res_no_auth = client.request(method, path, json=payload)
        assert res_no_auth.status_code == 401, f"Expected 401 for {path} without auth in LAN mode, got {res_no_auth.status_code}"
        assert "Authentication required" in res_no_auth.json().get("error", "")

        # With valid X-Nova-Auth header: should NOT return 401
        res_with_auth = client.request(method, path, json=payload, headers={"X-Nova-Auth": admin_token})
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



