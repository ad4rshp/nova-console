import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from app import config
from app.config import DB_PATH


def get_current_db_path() -> Path:
    import sys
    mod = sys.modules.get("app.database")
    if mod and hasattr(mod, "DB_PATH") and mod.DB_PATH != getattr(config, "DB_PATH", None):
        return Path(mod.DB_PATH)
    env_path = os.environ.get("NOVA_DB_PATH")
    if env_path:
        return Path(env_path)
    return getattr(config, "DB_PATH", DB_PATH)

def get_db() -> sqlite3.Connection:
    target_path = get_current_db_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        # Schema version tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # 1. Settings Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Request History Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS request_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL DEFAULT 0,
                iso_time TEXT DEFAULT '',
                endpoint TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_ms REAL DEFAULT 0.0,
                tps REAL DEFAULT 0.0,
                status_code INTEGER DEFAULT 200,
                token_source TEXT DEFAULT 'actual'
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_req_timestamp ON request_history(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_req_model ON request_history(model);")

        # Migrations: ensure request_history columns match active queries
        cursor.execute("PRAGMA table_info(request_history);")
        req_cols = {row["name"] for row in cursor.fetchall()}
        if "completion_tokens" not in req_cols:
            cursor.execute("ALTER TABLE request_history ADD COLUMN completion_tokens INTEGER DEFAULT 0;")
            if "output_tokens" in req_cols:
                cursor.execute("UPDATE request_history SET completion_tokens = output_tokens WHERE completion_tokens = 0;")
        if "iso_time" not in req_cols:
            cursor.execute("ALTER TABLE request_history ADD COLUMN iso_time TEXT DEFAULT '';")
        if "total_tokens" not in req_cols:
            cursor.execute("ALTER TABLE request_history ADD COLUMN total_tokens INTEGER DEFAULT 0;")
        if "latency_ms" not in req_cols:
            cursor.execute("ALTER TABLE request_history ADD COLUMN latency_ms REAL DEFAULT 0.0;")
        if "token_source" not in req_cols:
            cursor.execute("ALTER TABLE request_history ADD COLUMN token_source TEXT DEFAULT 'actual';")

        # 3. Modelfile History Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS modelfile_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL DEFAULT 0,
                iso_time TEXT DEFAULT '',
                content TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                parameters_json TEXT DEFAULT '{}',
                applied_to_ollama INTEGER DEFAULT 0
            );
        """)

        # Migrations: ensure modelfile_history columns exist
        cursor.execute("PRAGMA table_info(modelfile_history);")
        mf_cols = {row["name"] for row in cursor.fetchall()}
        for col_name, col_def in [
            ("iso_time", "TEXT DEFAULT ''"),
            ("content", "TEXT DEFAULT ''"),
            ("system_prompt", "TEXT DEFAULT ''"),
            ("parameters_json", "TEXT DEFAULT '{}'"),
            ("applied_to_ollama", "INTEGER DEFAULT 0"),
        ]:
            if col_name not in mf_cols:
                try:
                    cursor.execute(f"ALTER TABLE modelfile_history ADD COLUMN {col_name} {col_def};")
                except Exception:
                    pass

        # 4. Optional Chat History Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL DEFAULT 0,
                iso_time TEXT DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                thinking TEXT DEFAULT '',
                model TEXT NOT NULL,
                images TEXT DEFAULT ''
            );
        """)

        # Migration: ensure iso_time and images exist if table was created in an earlier build
        cursor.execute("PRAGMA table_info(chat_history);")
        chat_cols = {row["name"] for row in cursor.fetchall()}
        if "iso_time" not in chat_cols:
            try:
                cursor.execute("ALTER TABLE chat_history ADD COLUMN iso_time TEXT DEFAULT '';")
            except Exception:
                pass
        if "images" not in chat_cols:
            try:
                cursor.execute("ALTER TABLE chat_history ADD COLUMN images TEXT DEFAULT '';")
            except Exception:
                pass

        # 5. Terminal Command Audit Log Table (With permission status)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS command_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                command TEXT NOT NULL,
                working_dir TEXT NOT NULL,
                risk_level TEXT DEFAULT 'LOW',
                approved INTEGER DEFAULT 0,
                return_code INTEGER DEFAULT -1,
                output TEXT DEFAULT '',
                execution_time_s REAL DEFAULT 0.0
            );
        """)

        # Migration: ensure risk_level exists if table was created in an earlier build
        try:
            cursor.execute("ALTER TABLE command_audit_log ADD COLUMN risk_level TEXT DEFAULT 'LOW';")
        except Exception:
            pass

        # Default Settings
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('think', 'false');")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('save_chat_history', 'false');")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('preview_thinking', '\"summary\"');")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('theme', '\"light\"');")

        # Track schema version
        cursor.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (2);")
        conn.commit()

def db_get_settings(include_internal: bool = False) -> dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings;")
        rows = cursor.fetchall()
        settings = {}
        for row in rows:
            try:
                settings[row["key"]] = json.loads(row["value"])
            except Exception:
                settings[row["key"]] = row["value"]
        if not include_internal:
            settings.pop("admin_auth_token", None)
        return settings

def db_set_setting(key: str, value: Any) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        val_str = json.dumps(value)
        cursor.execute("""
            INSERT INTO settings (key, value, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP;
        """, (key, val_str))
        conn.commit()

def db_record_request(
    endpoint: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_s: float,
    tps: float,
    status_code: int = 200,
    token_source: str = "actual"
) -> None:
    now = time.time()
    iso_time = time.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute("""
            INSERT INTO request_history (timestamp, iso_time, endpoint, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, tps, status_code, token_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now,
            iso_time,
            endpoint,
            model,
            prompt_tokens,
            completion_tokens,
            prompt_tokens + completion_tokens,
            round(latency_s * 1000, 2),
            tps,
            status_code,
            token_source
        ))
        conn.commit()

def db_get_recent_requests(limit: int = 100) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT iso_time as time, endpoint as path, model, prompt_tokens, completion_tokens as output_tokens,
                   ROUND(latency_ms / 1000.0, 2) as latency_s, tps, status_code, token_source
            FROM request_history
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

def db_get_usage_metrics() -> dict[str, Any]:
    with get_db() as conn:
        agg = conn.execute("""
            SELECT COUNT(*) as req_count,
                   COALESCE(SUM(prompt_tokens), 0) as total_prompt,
                   COALESCE(SUM(completion_tokens), 0) as total_output,
                   COALESCE(AVG(latency_ms) / 1000.0, 0) as avg_lat
            FROM request_history
        """).fetchone()

        by_model_rows = conn.execute("""
            SELECT model, COUNT(*) as cnt FROM request_history GROUP BY model
        """).fetchall()
        by_model = {r["model"]: r["cnt"] for r in by_model_rows}

        recent_rows = conn.execute("""
            SELECT ROUND(latency_ms / 1000.0, 2) as lat, tps FROM request_history ORDER BY timestamp DESC LIMIT 10
        """).fetchall()
        rec_lat = round(sum(r["lat"] for r in recent_rows) / len(recent_rows), 2) if recent_rows else 0
        rec_tps_list = [r["tps"] for r in recent_rows if r["tps"] and r["tps"] > 0]
        rec_tps = round(sum(rec_tps_list) / len(rec_tps_list), 1) if rec_tps_list else 0

        # Exact vs estimated tokens breakdown
        actual_tokens = conn.execute("""
            SELECT COALESCE(SUM(total_tokens), 0) FROM request_history WHERE token_source = 'actual'
        """).fetchone()[0]
        estimated_tokens = conn.execute("""
            SELECT COALESCE(SUM(total_tokens), 0) FROM request_history WHERE token_source = 'estimated'
        """).fetchone()[0]

        return {
            "requests": agg["req_count"],
            "prompt_tokens": agg["total_prompt"],
            "output_tokens": agg["total_output"],
            "average_latency_s": rec_lat or round(agg["avg_lat"], 2),
            "avg_tps": rec_tps,
            "by_model": by_model,
            "tokens_breakdown": {
                "actual": actual_tokens,
                "estimated": estimated_tokens
            }
        }

def db_get_usage_summary() -> dict[str, Any]:
    with get_db() as conn:
        hourly = conn.execute("""
            SELECT strftime('%Y-%m-%d %H:00', datetime(timestamp, 'unixepoch', 'localtime')) as hour_bucket,
                   COUNT(*) as requests,
                   COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) as output_tokens,
                   ROUND(AVG(latency_ms), 1) as avg_latency_ms,
                   ROUND(AVG(CASE WHEN tps > 0 THEN tps ELSE NULL END), 1) as avg_tps
            FROM request_history
            WHERE timestamp >= ?
            GROUP BY hour_bucket
            ORDER BY hour_bucket DESC
            LIMIT 24
        """, (time.time() - 86400 * 7,)).fetchall()

        daily = conn.execute("""
            SELECT strftime('%Y-%m-%d', datetime(timestamp, 'unixepoch', 'localtime')) as day_bucket,
                   COUNT(*) as requests,
                   COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) as output_tokens,
                   ROUND(AVG(latency_ms), 1) as avg_latency_ms
            FROM request_history
            WHERE timestamp >= ?
            GROUP BY day_bucket
            ORDER BY day_bucket DESC
            LIMIT 14
        """, (time.time() - 86400 * 30,)).fetchall()

        return {
            "hourly": [dict(r) for r in hourly],
            "daily": [dict(r) for r in daily]
        }

def db_save_chat_message(role: str, content: str, thinking: str, model: str, images: Any = None) -> None:
    settings = db_get_settings()
    if not settings.get("save_chat_history", False):
        return
    images_str = json.dumps(images) if images else ""
    now = time.time()
    iso_now = time.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_history (timestamp, iso_time, role, content, thinking, model, images)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (now, iso_now, role, content, thinking, model, images_str))
        conn.commit()

def db_get_chat_history(limit: int = 100) -> list[dict[str, Any]]:
    """
    Returns the most recent chat messages up to limit, ordered chronologically.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content, thinking, model, timestamp, images 
            FROM (
                SELECT id, role, content, thinking, model, timestamp, images 
                FROM chat_history 
                ORDER BY id DESC 
                LIMIT ?
            )
            ORDER BY id ASC;
        """, (limit,))
        rows = []
        for r in cursor.fetchall():
            d = dict(r)
            if d.get("images"):
                try:
                    d["images"] = json.loads(d["images"])
                except Exception:
                    pass
            else:
                d["images"] = []
            rows.append(d)
        return rows

def db_clear_chat_history() -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM chat_history;")
        conn.commit()

def db_record_command(command: str, working_dir: str, approved: bool, return_code: int, output: str, execution_time: float, risk_level: str = "LOW") -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO command_audit_log (command, working_dir, risk_level, approved, return_code, output, execution_time_s)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (command, working_dir, risk_level, int(approved), return_code, output, round(execution_time, 3)))
        conn.commit()

def db_get_modelfile_history(limit: int = 10) -> list[dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, system_prompt, parameters_json, applied_to_ollama 
            FROM modelfile_history 
            ORDER BY id DESC 
            LIMIT ?;
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

def db_cleanup_old_records(retention_days: int = 30, max_requests: int = 20000) -> dict[str, int]:
    """
    Retention policy: Removes request and audit logs older than retention_days,
    and caps total request history rows to max_requests to prevent unbounded disk growth.
    """
    cutoff = time.time() - (retention_days * 86400)
    with get_db() as conn:
        c1 = conn.execute("DELETE FROM request_history WHERE timestamp < ?;", (cutoff,)).rowcount
        c2 = conn.execute("DELETE FROM command_audit_log WHERE timestamp < datetime('now', ?);", (f"-{retention_days} days",)).rowcount
        conn.execute("""
            DELETE FROM request_history WHERE id NOT IN (
                SELECT id FROM request_history ORDER BY id DESC LIMIT ?
            );
        """, (max_requests,))
        conn.commit()
        return {"deleted_requests": c1, "deleted_audit": c2}

def db_checkpoint() -> None:
    """
    Executes a WAL checkpoint to flush pending write transactions to the main DB file.
    """
    try:
        with get_db() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
        pass
