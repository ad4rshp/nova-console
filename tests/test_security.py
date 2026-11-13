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
