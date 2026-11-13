import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any
from app.config import WORKSPACE_DIR, COMMAND_TIMEOUT_SECONDS
from app.database import db_record_command

DANGEROUS_PATTERNS = [
    "format ",
    "rmdir /s /q c:",
    "rm -rf /",
    "rm -rf ~",
    ":(){ :|:& };:",
    "mkfs",
    "dd if=",
    "diskpart",
    "reg delete",
]

def assess_command_risk(command: str) -> dict[str, Any]:
    cmd_lower = command.strip().lower()

    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            return {
                "risk": "CRITICAL",
                "warning": f"Command contains potentially destructive operation ('{pattern.strip()}'). Proceed with extreme caution.",
                "color": "#ef4444"
            }

    write_verbs = ["rm ", "del ", "delete", "move ", "mv ", "git push", "git reset", "drop ", "truncate", "shutdown", "reboot"]
    for verb in write_verbs:
        if verb in cmd_lower:
            return {
                "risk": "HIGH",
                "warning": "Command modifies or removes files or system state.",
                "color": "#f59e0b"
            }

    read_verbs = ["ls", "dir", "pwd", "cd ", "cat ", "type ", "echo ", "git status", "git log", "git diff", "python ", "pip list", "npm list", "whoami", "hostname", "curl"]
    for verb in read_verbs:
        if cmd_lower.startswith(verb) or f" {verb}" in cmd_lower:
            return {
                "risk": "LOW",
                "warning": "Safe read/inspection command.",
                "color": "#10b981"
            }

    return {
        "risk": "MEDIUM",
        "warning": "Standard system command. Review before approving.",
        "color": "#3b82f6"
    }

def run_system_command(command: str, working_dir: str | None = None, approved: bool = False) -> dict[str, Any]:
    if not approved:
        return {
            "ok": False,
            "error": "Execution declined: explicit user approval is required.",
            "return_code": -1,
            "output": ""
        }

    target_dir = Path(working_dir).resolve() if working_dir else WORKSPACE_DIR
    if not target_dir.exists():
        target_dir = WORKSPACE_DIR

    assessment = assess_command_risk(command)
    risk_level = assessment.get("risk", "LOW")

    start_time = time.perf_counter()
    shell_cmd = command.strip()

    is_windows = platform.system() == "Windows"
    try:
        if is_windows:
            # Use PowerShell for modern Windows command execution
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", shell_cmd],
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS
            )
        else:
            result = subprocess.run(
                shell_cmd,
                shell=True,
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS
            )

        duration = time.perf_counter() - start_time
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        combined_output = (stdout + ("\n--- STDERR ---\n" + stderr if stderr else "")).strip()

        # Cap output to 64KB for safety
        if len(combined_output) > 65536:
            combined_output = combined_output[:65536] + "\n... [Output truncated at 64KB]"

        db_record_command(command, str(target_dir), approved=True, return_code=result.returncode, output=combined_output, execution_time=duration, risk_level=risk_level)

        return {
            "ok": result.returncode == 0,
            "return_code": result.returncode,
            "output": combined_output or "(Command completed with no output)",
            "execution_time_s": round(duration, 2),
            "working_dir": str(target_dir),
            "risk_level": risk_level
        }

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start_time
        error_msg = f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds."
        db_record_command(command, str(target_dir), approved=True, return_code=-1, output=error_msg, execution_time=duration, risk_level=risk_level)
        return {
            "ok": False,
            "error": error_msg,
            "return_code": -1,
            "output": error_msg,
            "execution_time_s": round(duration, 2),
            "risk_level": risk_level
        }
    except Exception as exc:
        duration = time.perf_counter() - start_time
        error_msg = f"Execution failed: {str(exc)}"
        db_record_command(command, str(target_dir), approved=True, return_code=-1, output=error_msg, execution_time=duration, risk_level=risk_level)
        return {
            "ok": False,
            "error": error_msg,
            "return_code": -1,
            "output": error_msg,
            "execution_time_s": round(duration, 2),
            "risk_level": risk_level
        }

