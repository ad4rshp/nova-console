from app.database import (
    db_clear_chat_history,
    db_get_chat_history,
    db_get_recent_requests,
    db_get_usage_metrics,
    db_record_command,
    db_record_request,
    db_save_chat_message,
    db_set_setting,
    get_db,
    init_db,
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
    db_clear_chat_history()
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
    monkeypatch.setenv("NOVA_DB_PATH", str(legacy_db_file))
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

def test_token_source_tracking_actual_vs_estimated():
    """Ensure exact provider-reported tokens and character-estimated tokens are recorded distinctly."""
    # Record one actual and one estimated request
    db_record_request(
        endpoint="/v1/chat/completions",
        model="test-exact-model",
        prompt_tokens=100,
        completion_tokens=50,
        latency_s=1.0,
        tps=50.0,
        status_code=200,
        token_source="actual"
    )
    db_record_request(
        endpoint="/v1/chat/completions",
        model="test-est-model",
        prompt_tokens=200,
        completion_tokens=80,
        latency_s=1.5,
        tps=53.3,
        status_code=200,
        token_source="estimated"
    )

    recent = db_get_recent_requests(10)
    exact_req = next((r for r in recent if r["model"] == "test-exact-model"), None)
    est_req = next((r for r in recent if r["model"] == "test-est-model"), None)

    assert exact_req is not None
    assert exact_req["token_source"] == "actual"

    assert est_req is not None
    assert est_req["token_source"] == "estimated"

    metrics = db_get_usage_metrics()
    assert "tokens_breakdown" in metrics
    assert metrics["tokens_breakdown"]["actual"] >= 150
    assert metrics["tokens_breakdown"]["estimated"] >= 280

def test_chat_history_retrieval_returns_latest_chronological():
    """Ensure db_get_chat_history returns the latest messages, not the oldest from inception."""
    from app.database import db_clear_chat_history, db_get_chat_history, db_save_chat_message, db_set_setting
    db_set_setting("save_chat_history", True)
    db_clear_chat_history()

    # Insert 10 sequential messages
    for i in range(1, 11):
        db_save_chat_message("user", f"Message {i}", "", "test-model")

    # Fetch with limit=5: Must return messages 6, 7, 8, 9, 10 in chronological order
    recent_5 = db_get_chat_history(limit=5)
    assert len(recent_5) == 5
    contents = [m["content"] for m in recent_5]
    assert contents == ["Message 6", "Message 7", "Message 8", "Message 9", "Message 10"]

def test_database_cleanup_retention():
    """Ensure db_cleanup_old_records purges expired entries and caps table sizes."""
    from app.database import db_cleanup_old_records, db_record_request, get_db
    # Record requests
    for i in range(15):
        db_record_request(f"/v1/test/{i}", "test-model", 10, 10, 0.1, 10.0)

    # Cleanup with a small max_requests limit of 5
    result = db_cleanup_old_records(retention_days=30, max_requests=5)
    assert "deleted_requests" in result

    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM request_history;").fetchone()[0]
        assert count <= 5

def test_database_test_isolation_guarantee():
    """Ensure tests run against an isolated temporary database, never modifying the production DB."""
    import os

    from app.config import BASE_DIR
    from app.database import get_current_db_path

    current_db = get_current_db_path()
    real_repo_db = BASE_DIR / "nova-dashboard.db"

    # Must NOT point to the real repository database
    assert str(current_db.resolve()) != str(real_repo_db.resolve())
    assert "nova-test-suite" in str(current_db) or "tmp" in str(current_db).lower() or "temp" in str(current_db).lower()
    assert os.environ.get("NOVA_TEST_MODE") == "1"


