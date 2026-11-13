import os
import platform
import re
import secrets
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from app.config import WORKSPACE_DIR, COMMAND_TIMEOUT_SECONDS
from app.database import db_record_command

# Server-side single-use cryptographic approval storage
_APPROVAL_TOKENS: dict[str, dict[str, Any]] = {}
_TOKENS_LOCK = threading.Lock()
TOKEN_TTL_SECONDS = 60.0  # Tokens expire in 60 seconds

# Absolute destructive blacklist (Blocked completely, never allowed)
CATASTROPHIC_PATTERNS = [
    r"\bformat\b\s+[a-z]:",
    r"\brmdir\b\s+.*[c-z]:\\",
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+/(?:$|\s)",
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+~",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bdiskpart\b",
    r"\breg\s+delete\b",
    r"powershell.*downloadstring",
    r"powershell.*invoke-expression",
    r"\bcertutil\b.*-urlcache",
]

DANGEROUS_PATTERNS = [
    "format ",
    "rmdir /s /q",
    "rm -rf",
    "mkfs",
    "diskpart",
    "reg delete",
    "drop database",
    "drop table",
]

def validate_working_dir(requested_path: str | None) -> Path:
    """
    Validates and bounds the working directory strictly to within WORKSPACE_DIR.
    Prevents path traversal, symlink escapes, and system directory tampering.
    """
    base_workspace = WORKSPACE_DIR.resolve()
    if not requested_path:
        return base_workspace

    target = Path(requested_path).resolve()

    # Verify target is contained within approved workspace root
    try:
        target.relative_to(base_workspace)
    except ValueError:
        # Path traversal attempted outside workspace boundary
        return base_workspace

    if not target.exists() or not target.is_dir():
        return base_workspace

    return target

def assess_command_risk(command: str) -> dict[str, Any]:
    """
    Analyzes command safety and returns a risk category and warning.
    """
    cmd_lower = command.strip().lower()

    for pattern in CATASTROPHIC_PATTERNS:
        if re.search(pattern, cmd_lower):
            return {
                "risk": "CRITICAL",
                "warning": "Catastrophic command detected. This operation is blocked by security policy.",
                "color": "#ef4444",
                "blocked": True
            }

    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            return {
                "risk": "CRITICAL",
                "warning": f"Command contains high-risk operation ('{pattern.strip()}'). Proceed with extreme caution.",
                "color": "#ef4444",
                "blocked": False
            }

    write_verbs = ["rm ", "del ", "delete", "move ", "mv ", "git push", "git reset", "drop ", "truncate", "shutdown", "reboot", "kill ", "taskkill"]
    for verb in write_verbs:
        if verb in cmd_lower:
            return {
                "risk": "HIGH",
                "warning": "Command modifies files or system processes.",
                "color": "#f59e0b",
                "blocked": False
            }

    read_verbs = ["ls", "dir", "pwd", "cd ", "cat ", "type ", "echo ", "git status", "git log", "git diff", "python ", "pip list", "npm list", "whoami", "hostname", "curl"]
    for verb in read_verbs:
        if cmd_lower.startswith(verb) or f" {verb}" in cmd_lower:
            return {
                "risk": "LOW",
                "warning": "Safe read/inspection command.",
                "color": "#10b981",
                "blocked": False
            }

    return {
        "risk": "MEDIUM",
        "warning": "Standard system command. Review before approving.",
        "color": "#3b82f6",
        "blocked": False
    }

def generate_approval_token(command: str, working_dir: str | None = None) -> dict[str, Any]:
    """
    Generates a cryptographically random, short-lived, single-use server authorization token.
    Binds the token to the exact command and working directory.
    """
    cmd_clean = command.strip()
    target_dir = validate_working_dir(working_dir)
    assessment = assess_command_risk(cmd_clean)

    now = time.time()
    with _TOKENS_LOCK:
        # Prune expired tokens
        expired = [k for k, v in _APPROVAL_TOKENS.items() if now > v["expires_at"]]
        for k in expired:
            del _APPROVAL_TOKENS[k]

        token = secrets.token_urlsafe(32)
        _APPROVAL_TOKENS[token] = {
            "command": cmd_clean,
            "working_dir": str(target_dir),
            "created_at": now,
            "expires_at": now + TOKEN_TTL_SECONDS,
            "used": False,
            "risk_level": assessment["risk"]
        }

    return {
        "approval_token": token,
        "expires_in_s": int(TOKEN_TTL_SECONDS),
        "command": cmd_clean,
        "working_dir": str(target_dir),
        **assessment
    }

def verify_and_consume_token(token: str, command: str, working_dir: str | None = None) -> tuple[bool, str, dict[str, Any] | None]:
    """
    Validates that the token is valid, unexpired, matches command & working directory, and has not been used.
    Immediately invalidates the token upon successful verification.
    """
    if not token or not isinstance(token, str):
        return False, "Missing or invalid approval token.", None

    now = time.time()
    with _TOKENS_LOCK:
        record = _APPROVAL_TOKENS.get(token)
        if not record:
            return False, "Invalid or unrecognized approval token.", None

        if record["used"]:
            return False, "Approval token has already been consumed (replay attack prevented).", None

        if now > record["expires_at"]:
            del _APPROVAL_TOKENS[token]
            return False, "Approval token has expired.", None

        if record["command"] != command.strip():
            return False, "Command tampering detected: token does not authorize this modified command.", None

        expected_dir = str(validate_working_dir(working_dir))
        if record["working_dir"] != expected_dir:
            return False, "Working directory mismatch: token does not authorize execution in this directory.", None

        # Consume token immediately
        record["used"] = True
        del _APPROVAL_TOKENS[token]
        return True, "Authorized", record

def _kill_process_tree(proc: subprocess.Popen, is_windows: bool):
    """
    Terminates the entire process tree to prevent orphaned background processes.
    """
    try:
        if is_windows:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def scrub_sensitive_output(text: str) -> str:
    """
    Scrubs potential API keys, passwords, or tokens from output before logging or rendering.
    """
    # Scrub Bearer / sk- / basic auth patterns
    scrubbed = re.sub(r"(?i)(bearer\s+|api[_-]?key\s*[:=]\s*['\"]?|sk-[a-zA-Z0-9]{20,})([a-zA-Z0-9_\-\.]{8,})", r"\1[REDACTED]", text)
    return scrubbed

def run_system_command(
    command: str,
    working_dir: str | None = None,
    approval_token: str | None = None
) -> dict[str, Any]:
    """
    Executes a system command with strict server-side authorization and process isolation.
    """
    target_dir = validate_working_dir(working_dir)
    cmd_clean = command.strip()

    # 1. Enforce Server-Side Token Authorization
    valid, reason, token_data = verify_and_consume_token(approval_token or "", cmd_clean, str(target_dir))
    if not valid:
        return {
            "ok": False,
            "error": f"Execution declined: {reason}",
            "return_code": 403,
            "output": "",
            "working_dir": str(target_dir)
        }

    assessment = assess_command_risk(cmd_clean)
    if assessment.get("blocked", False):
        return {
            "ok": False,
            "error": f"Execution blocked by security policy: {assessment.get('warning')}",
            "return_code": 403,
            "output": "",
            "working_dir": str(target_dir)
        }

    risk_level = assessment.get("risk", "MEDIUM")
    start_time = time.perf_counter()
    is_windows = platform.system() == "Windows"

    proc = None
    try:
        if is_windows:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd_clean],
                cwd=str(target_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            proc = subprocess.Popen(
                cmd_clean,
                shell=True,
                cwd=str(target_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid
            )

        try:
            stdout, stderr = proc.communicate(timeout=COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc, is_windows)
            duration = time.perf_counter() - start_time
            error_msg = f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds. Process tree terminated."
            db_record_command(cmd_clean, str(target_dir), approved=True, return_code=-1, output=error_msg, execution_time=duration, risk_level=risk_level)
            return {
                "ok": False,
                "error": error_msg,
                "return_code": -1,
                "output": error_msg,
                "execution_time_s": round(duration, 2),
                "working_dir": str(target_dir),
                "risk_level": risk_level
            }

        duration = time.perf_counter() - start_time
        combined_output = ((stdout or "") + ("\n--- STDERR ---\n" + (stderr or "") if stderr else "")).strip()

        # Cap output to 64KB for safety
        if len(combined_output) > 65536:
            combined_output = combined_output[:65536] + "\n... [Output truncated at 64KB]"

        safe_output = scrub_sensitive_output(combined_output)
        db_record_command(
            cmd_clean,
            str(target_dir),
            approved=True,
            return_code=proc.returncode,
            output=safe_output,
            execution_time=duration,
            risk_level=risk_level
        )

        return {
            "ok": proc.returncode == 0,
            "return_code": proc.returncode,
            "output": safe_output or "(Command completed with no output)",
            "execution_time_s": round(duration, 2),
            "working_dir": str(target_dir),
            "risk_level": risk_level
        }

    except Exception as exc:
        duration = time.perf_counter() - start_time
        error_msg = f"Execution failed: {str(exc)}"
        db_record_command(cmd_clean, str(target_dir), approved=True, return_code=-1, output=error_msg, execution_time=duration, risk_level=risk_level)
        return {
            "ok": False,
            "error": error_msg,
            "return_code": -1,
            "output": error_msg,
            "execution_time_s": round(duration, 2),
            "working_dir": str(target_dir),
            "risk_level": risk_level
        }
