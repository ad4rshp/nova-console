import time
import pytest
from app.database import (
    init_db,
    get_db,
    db_record_request,
    db_get_recent_requests,
    db_get_usage_metrics,
    db_get_usage_summary,
    db_save_chat_message,
    db_get_chat_history,
    db_clear_chat_history,
    db_set_setting,
    db_get_settings,
    db_record_command,
)

def test_database_initialization_and_schema():
    """Ensure init_db creates all required tables with expected canonical columns."""
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        # Verify request_history schema
        cursor.execute("PRAGMA table_info(request_history);")
        cols = {row["name"] for row in cursor.fetchall()}
        required_cols = {"id", "timestamp", "iso_time", "endpoint", "model", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "tps", "status_code"}
        assert required_cols.issubset(cols), f"Missing columns: {required_cols - cols}"

        # Verify modelfile_history schema
        cursor.execute("PRAGMA table_info(modelfile_history);")
        mf_cols = {row["name"] for row in cursor.fetchall()}
        assert {"timestamp", "iso_time", "system_prompt", "parameters_json"}.issubset(mf_cols)

        # Verify command_audit_log schema
        cursor.execute("PRAGMA table_info(command_audit_log);")
        audit_cols = {row["name"] for row in cursor.fetchall()}
        assert {"command", "working_dir", "risk_level", "approved", "output"}.issubset(audit_cols)

def test_db_record_request_and_metrics():
    """Ensure requests are properly recorded and metrics aggregated without schema errors."""
    db_record_request(
        endpoint="/v1/chat/completions",
        model="qwen-coder:7b",
        prompt_tokens=150,
        completion_tokens=75,
        latency_s=1.5,
        tps=50.0,
        status_code=200
    )

    recent = db_get_recent_requests(5)
    assert len(recent) > 0
    latest = recent[0]
    assert latest["model"] == "qwen-coder:7b"
    assert latest["output_tokens"] == 75

    metrics = db_get_usage_metrics()
    assert metrics["requests"] >= 1
    assert metrics["output_tokens"] >= 75
    assert "qwen-coder:7b" in metrics["by_model"]

def test_chat_history_lifecycle():
    """Ensure chat messages respect privacy settings (disabled by default) and clear cleanly."""
    # 1. By default, save_chat_history is False, so messages are NOT stored in SQLite (Privacy by default)
    db_set_setting("save_chat_history", False)
    db_save_chat_message("user", "Private message not stored", "", "nova:latest")
    assert len(db_get_chat_history()) == 0

    # 2. When explicitly enabled by user, messages are stored
    db_set_setting("save_chat_history", True)
    db_save_chat_message("user", "Hello database test", "", "nova:latest")
    db_save_chat_message("assistant", "Hello from test suite", "Reasoning step", "nova:latest")

    history = db_get_chat_history()
    assert len(history) >= 2
    assert any(m["content"] == "Hello database test" for m in history)

    # 3. Clear chat history
    db_clear_chat_history()
    cleared = db_get_chat_history()
    assert len(cleared) == 0

def test_command_audit_logging():
    """Ensure command executions are recorded in the audit log."""
    db_record_command(
        command="git status",
        working_dir="/test",
        approved=True,
        return_code=0,
        output="On branch main",
        execution_time=0.15,
        risk_level="LOW"
    )

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM command_audit_log WHERE command = 'git status' ORDER BY id DESC LIMIT 1;")
        row = cursor.fetchone()
        assert row is not None
        assert row["risk_level"] == "LOW"
        assert row["approved"] == 1
