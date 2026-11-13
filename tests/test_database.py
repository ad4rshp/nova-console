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

def test_database_migrations_idempotency(tmp_path, monkeypatch):
    """
    Ensure init_db safely migrates a legacy database schema with missing columns
    (e.g., v1 without completion_tokens or risk_level) without data loss or crashes.
    """
    import sqlite3
    legacy_db_file = tmp_path / "legacy_test.db"
    
    # 1. Create a legacy v1.0 SQLite schema with missing columns
    conn = sqlite3.connect(str(legacy_db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE request_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL DEFAULT 0,
            endpoint TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            status_code INTEGER DEFAULT 200
        );
    """)
    # Insert legacy data
    cur.execute("""
        INSERT INTO request_history (timestamp, endpoint, model, prompt_tokens, output_tokens, status_code)
        VALUES (1700000000.0, '/v1/chat/completions', 'legacy-model', 100, 50, 200);
    """)

    cur.execute("""
        CREATE TABLE chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT NOT NULL
        );
    """)
    cur.execute("""
        INSERT INTO chat_history (role, content, model)
        VALUES ('user', 'Legacy message preserved', 'legacy-model');
    """)

    cur.execute("""
        CREATE TABLE command_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command TEXT NOT NULL,
            working_dir TEXT NOT NULL,
            approved INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()

    # 2. Point app database path to the legacy database file and run init_db
    monkeypatch.setattr("app.database.DB_PATH", legacy_db_file)
    init_db()

    # 3. Verify migration succeeded without data loss
    migrated_conn = sqlite3.connect(str(legacy_db_file))
    migrated_conn.row_factory = sqlite3.Row
    m_cur = migrated_conn.cursor()

    # Verify request_history has completion_tokens migrated from output_tokens
    m_cur.execute("SELECT * FROM request_history WHERE model = 'legacy-model';")
    req_row = m_cur.fetchone()
    assert req_row is not None
    assert req_row["completion_tokens"] == 50
    assert req_row["prompt_tokens"] == 100
    assert "latency_ms" in req_row.keys()

    # Verify chat_history retained existing row and added images/iso_time columns
    m_cur.execute("SELECT * FROM chat_history WHERE model = 'legacy-model';")
    chat_row = m_cur.fetchone()
    assert chat_row is not None
    assert chat_row["content"] == "Legacy message preserved"
    assert "images" in chat_row.keys()
    assert "iso_time" in chat_row.keys()

    # Verify command_audit_log added risk_level
    m_cur.execute("PRAGMA table_info(command_audit_log);")
    audit_cols = {r["name"] for r in m_cur.fetchall()}
    assert "risk_level" in audit_cols

    migrated_conn.close()
