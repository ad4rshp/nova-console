import os
import platform
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.config import COMMAND_TIMEOUT_SECONDS, WORKSPACE_DIR
from app.database import db_record_command

# Server-side single-use cryptographic approval storage
_APPROVAL_TOKENS: dict[str, dict[str, Any]] = {}
_TOKENS_LOCK = threading.Lock()
TOKEN_TTL_SECONDS = 60.0  # Tokens expire in 60 seconds

# Terminal concurrency semaphore (Max 3 concurrent executions to prevent CPU/fork exhaustion)
MAX_CONCURRENT_TERMINAL_COMMANDS = int(os.environ.get("NOVA_MAX_CONCURRENT_COMMANDS", "3"))
_TERMINAL_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_TERMINAL_COMMANDS)

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

def get_restricted_path() -> str:
    """
    Constructs a hardened, restricted PATH containing strictly standard system binaries
    and the active Python virtual environment. Prevents execution of binaries from untrusted directories.
    """
    safe_dirs: list[str] = []
    py_bin = Path(sys.executable).parent
    safe_dirs.append(str(py_bin))

    if platform.system() == "Windows":
        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        safe_dirs.extend([
            os.path.join(sys_root, "System32"),
            sys_root,
            os.path.join(sys_root, "System32", "WindowsPowerShell", "v1.0"),
            os.path.join(sys_root, "System32", "OpenSSH"),
        ])
    else:
        safe_dirs.extend([
            "/usr/bin",
            "/bin",
            "/usr/local/bin",
            "/usr/sbin",
            "/sbin",
        ])

    sep = ";" if platform.system() == "Windows" else ":"
    existing = [d for d in safe_dirs if os.path.isdir(d)]
    return sep.join(existing)

def _setup_posix_sandbox():
    """Sets process group and configures OS resource limits on Linux/macOS."""
    os.setsid()
    try:
        import resource
        # Maximum CPU time (15s soft, 20s hard)
        resource.setrlimit(resource.RLIMIT_CPU, (15, 20))
        # Maximum virtual memory / address space (1GB)
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        # Maximum file write size (25MB)
        resource.setrlimit(resource.RLIMIT_FSIZE, (25 * 1024 * 1024, 25 * 1024 * 1024))
        # Maximum open file descriptors
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        # Maximum subprocesses to prevent fork bombs
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except Exception:
        pass

def is_strict_sandbox() -> bool:
    return os.environ.get("NOVA_TERMINAL_SANDBOX", "0").lower() in ("strict", "1", "true", "yes")

def is_terminal_globally_enabled() -> bool:
    """Checks whether terminal execution is enabled on this system."""
    if os.environ.get("NOVA_DISABLE_TERMINAL", "0").lower() in ("1", "true", "yes"):
        return False
    return True

def validate_command_chaining(command: str) -> tuple[bool, str]:
    """
    Detects shell chaining operators (;, &&, ||, |, &, `, $()) that can be used
    for command injection or unauthorized lateral execution.
    """
    if is_strict_sandbox():
        pattern = r"(;|&&|\|\||\|(?![&|])|(?<!&)&(?!&)|`|\$\()"
        if re.search(pattern, command):
            return False, "Command chaining and subshell operators (;, &&, ||, |, &, `, $()) are strictly forbidden when NOVA_TERMINAL_SANDBOX=strict."
    return True, ""

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

    # Check strict sandbox chaining rules
    chain_ok, chain_msg = validate_command_chaining(cmd_lower)
    if not chain_ok:
        return {
            "risk": "CRITICAL",
            "warning": chain_msg,
            "color": "#ef4444",
            "blocked": True
        }

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
    approval_token: str | None = None,
    user_authorization: str | None = None
) -> dict[str, Any]:
    """
    Executes a system command with strict server-side authorization and process isolation.
    Requires BOTH:
    1. Valid server-side user authorization credential.
    2. Cryptographic single-use command approval token.
    """
    target_dir = validate_working_dir(working_dir)
    cmd_clean = command.strip()

    if os.environ.get("NOVA_DISABLE_TERMINAL", "0").lower() in ("1", "true", "yes"):
        return {
            "ok": False,
            "error": "Terminal command execution is disabled by server security policy (NOVA_DISABLE_TERMINAL).",
            "return_code": 403,
            "output": "",
            "working_dir": str(target_dir)
        }

    # Defense in depth: Disable terminal execution by default for network-exposed LAN deployments
    import sys

    from app import config
    app_main = sys.modules.get("app.main")
    main_lan = getattr(app_main, "NOVA_ALLOW_LAN", False) if app_main else False
    config_lan = getattr(config, "NOVA_ALLOW_LAN", False)
    lan_active = main_lan or config_lan
    is_lan_terminal_enabled = os.environ.get("NOVA_ENABLE_TERMINAL_LAN", "0").lower() in ("1", "true", "yes")
    if lan_active and not is_lan_terminal_enabled:
        return {
            "ok": False,
            "error": "Terminal execution is disabled by default on network-exposed deployments (NOVA_ALLOW_LAN=1). Set NOVA_ENABLE_TERMINAL_LAN=1 to explicitly permit terminal commands over LAN.",
            "return_code": 403,
            "output": "",
            "working_dir": str(target_dir)
        }

    # Configurable command allowlist enforcement
    allowlist_env = os.environ.get("NOVA_COMMAND_ALLOWLIST", "").strip()
    strict_allowlist = os.environ.get("NOVA_STRICT_ALLOWLIST", "0").lower() in ("1", "true", "yes") or bool(allowlist_env)
    if strict_allowlist:
        allowed_bins = [b.strip().lower() for b in allowlist_env.split(",") if b.strip()] if allowlist_env else [
            "python", "python3", "pip", "pip3", "pytest", "git", "dir", "ls", "echo", "type", "cat", "node", "npm", "whoami", "hostname"
        ]
        import shlex
        try:
            tokens = shlex.split(cmd_clean, posix=(platform.system() != "Windows"))
            base_cmd = Path(tokens[0]).name.lower() if tokens else ""
            if base_cmd.endswith(".exe"):
                base_cmd = base_cmd[:-4]
        except Exception:
            base_cmd = cmd_clean.split()[0].lower() if cmd_clean.split() else ""

        if base_cmd not in allowed_bins:
            return {
                "ok": False,
                "error": f"Execution blocked: Command '{base_cmd}' is not in the approved command allowlist.",
                "return_code": 403,
                "output": "",
                "working_dir": str(target_dir)
            }

    # 1. Enforce Server-Side User Authorization
    from app.services.auth import verify_admin_token
    if not verify_admin_token(user_authorization):
        return {
            "ok": False,
            "error": "Execution declined: valid server-side user authorization credential required.",
            "return_code": 401,
            "output": "",
            "working_dir": str(target_dir)
        }

    # 2. Enforce Server-Side Single-Use Token Authorization
    valid, reason, token_data = verify_and_consume_token(approval_token or "", cmd_clean, str(target_dir))
    if not valid:
        return {
            "ok": False,
            "error": f"Execution declined: {reason}",
            "return_code": 403,
            "output": "",
            "working_dir": str(target_dir)
        }

    # 3. Enforce Strict Sandbox Command Rules
    chain_ok, chain_msg = validate_command_chaining(cmd_clean)
    if not chain_ok:
        return {
            "ok": False,
            "error": chain_msg,
            "return_code": 403,
            "output": "",
            "working_dir": str(target_dir),
            "risk_level": "BLOCKED"
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

    # 4. Enforce Concurrency Semaphore (Max 3 concurrent executions)
    acquired = _TERMINAL_SEMAPHORE.acquire(blocking=True, timeout=2.0)
    if not acquired:
        return {
            "ok": False,
            "error": "Terminal execution concurrency limit reached (max 3 concurrent processes).",
            "return_code": 429,
            "output": "",
            "working_dir": str(target_dir),
            "risk_level": "BLOCKED"
        }

    risk_level = assessment.get("risk", "MEDIUM")
    start_time = time.perf_counter()
    is_windows = platform.system() == "Windows"

    # Restricted environment: prevent subprocess from inheriting host secrets or API credentials
    safe_env = os.environ.copy()
    secret_terms = ("NOVA", "TOKEN", "SECRET", "KEY", "PASS", "AUTH", "CREDENTIAL", "AWS", "GITHUB", "OPENAI")
    for k in list(safe_env.keys()):
        if any(term in k.upper() for term in secret_terms):
            safe_env.pop(k, None)

    if is_windows:
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags |= subprocess.CREATE_NO_WINDOW
    else:
        creation_flags = 0

    # Restrict PATH to safe system locations and virtual environment
    safe_env["PATH"] = get_restricted_path()

    proc = None
    try:
        if is_windows:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd_clean],
                cwd=str(target_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
                creationflags=creation_flags
            )
        else:
            bash_cmd = ["/bin/bash", "--noprofile", "--norc"]
            if is_strict_sandbox():
                bash_cmd.append("--restricted")
            bash_cmd.extend(["-c", cmd_clean])
            proc = subprocess.Popen(
                bash_cmd,
                shell=False,
                cwd=str(target_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
                preexec_fn=_setup_posix_sandbox
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
    finally:
        _TERMINAL_SEMAPHORE.release()
