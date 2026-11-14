import ipaddress
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Base Paths (Fully dynamic, supports standalone .exe / PyInstaller / Frozen mode)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BUNDLE_DIR = Path(sys._MEIPASS)
    BASE_DIR = Path(sys.executable).resolve().parent
    STATIC_DIR = BUNDLE_DIR
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    STATIC_DIR = BASE_DIR

db_env = os.environ.get("NOVA_DB_PATH")
if db_env:
    DB_PATH = Path(db_env)
elif getattr(sys, "frozen", False):
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        data_dir = Path(local_appdata) / "NovaConsole" / "data"
    else:
        data_dir = Path.home() / ".local" / "share" / "nova-console"
    data_dir.mkdir(parents=True, exist_ok=True)
    DB_PATH = data_dir / "nova-dashboard.db"
else:
    DB_PATH = BASE_DIR / "nova-dashboard.db"
mf_env = os.environ.get("NOVA_MODELFILE_PATH")
if mf_env:
    MODELFILE_PATH = Path(mf_env)
elif getattr(sys, "frozen", False):
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        config_dir = Path(local_appdata) / "NovaConsole" / "config"
    else:
        config_dir = Path.home() / ".config" / "nova-console"
    config_dir.mkdir(parents=True, exist_ok=True)
    MODELFILE_PATH = config_dir / "Modelfile"
    if not MODELFILE_PATH.exists():
        bundled_mf = (BUNDLE_DIR if hasattr(sys, "_MEIPASS") else BASE_DIR) / "app" / "Modelfile"
        if bundled_mf.exists():
            try:
                import shutil
                shutil.copy2(bundled_mf, MODELFILE_PATH)
            except Exception:
                pass
else:
    MODELFILE_PATH = BASE_DIR / "app" / "Modelfile"
    if not MODELFILE_PATH.exists() and (BASE_DIR / "Modelfile").exists():
        MODELFILE_PATH = BASE_DIR / "Modelfile"
TEMPLATES_DIR = (BUNDLE_DIR if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else BASE_DIR) / "app" / "templates"

# Network & Host Binding Validation
# Security Rule: Default strictly to 127.0.0.1 (Localhost Only).
# Any non-loopback bind address (0.0.0.0, LAN IP, public IP) MANDATES NOVA_ALLOW_LAN=1.

def is_loopback_host(host_str: str) -> bool:
    """
    Determines whether a host string is a strict loopback address.
    Returns True for localhost, 127.0.0.1, ::1, or testserver.
    Returns False for 0.0.0.0, ::, LAN interfaces, or public domains.
    """
    if not host_str:
        return False
    host_clean = host_str.strip().lower().strip("[]")
    if host_clean in ("localhost", "127.0.0.1", "::1", "testserver"):
        return True
    try:
        ip = ipaddress.ip_address(host_clean)
        return ip.is_loopback
    except ValueError:
        # Non-IP hostnames (e.g. 0.0.0.0, custom domain) are not loopback
        return False

def validate_bind_host(raw_host: str, allow_lan: bool) -> str:
    """
    Validates the bind host against security policies.
    Requires NOVA_ALLOW_LAN=1 for any non-loopback host address.
    """
    cleaned = raw_host.strip() if raw_host else ""
    if not cleaned:
        return "0.0.0.0" if allow_lan else "127.0.0.1"

    if is_loopback_host(cleaned):
        return cleaned

    # Non-loopback address requested
    if not allow_lan:
        raise ValueError(
            f"Security Violation: Binding to non-loopback address '{cleaned}' requires NOVA_ALLOW_LAN=1. "
            f"Set NOVA_ALLOW_LAN=1 to explicitly authorize network exposure."
        )
    return cleaned

NOVA_ALLOW_LAN = os.environ.get("NOVA_ALLOW_LAN", "0").lower() in ("1", "true", "yes")
_env_host = os.environ.get("NOVA_HOST", "").strip()

try:
    HOST = validate_bind_host(_env_host, NOVA_ALLOW_LAN)
except ValueError:
    # If invalid host provided in environment without NOVA_ALLOW_LAN, raise to stop execution
    # or fallback to loopback if running in safe mode
    if os.environ.get("NOVA_SAFE_FALLBACK", "0") == "1":
        HOST = "127.0.0.1"
    else:
        raise

try:
    PORT = int(os.environ.get("NOVA_PORT", os.environ.get("PORT", 8080)))
    if not (1 <= PORT <= 65535):
        PORT = 8080
except (ValueError, TypeError):
    PORT = 8080

def redact_url_credentials(url_str: str) -> str:
    """Redacts credentials and passwords from URL strings for safe logging and diagnostics."""
    try:
        p = urlparse(url_str)
        if p.password:
            return url_str.replace(f":{p.password}@", ":[REDACTED]@")
        return url_str
    except Exception:
        return url_str

# Universal Inference Engine (Ollama: 11434, LM Studio: 1234, vLLM: 8000, LocalAI: 8080, custom OpenAI endpoint)
def validate_backend_url(raw_url: str) -> str:
    """
    Validates the LLM backend URL to prevent SSRF and credential leakage vulnerabilities.
    Enforces http/https schemes, prohibits embedded credentials, and blocks dangerous targets
    such as cloud metadata endpoints and link-local addresses across both raw IPs and resolved DNS hostnames.
    """
    import socket

    cleaned = raw_url.strip().rstrip("/") if raw_url else ""
    if not cleaned:
        return "http://127.0.0.1:11434"

    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(
            f"Security Violation: Backend URL scheme must be http or https, received '{scheme}'."
        )

    if parsed.username or parsed.password:
        raise ValueError("Security Violation: Embedded credentials in backend URL are prohibited. Use NOVA_BACKEND_API_KEY instead.")

    hostname = (parsed.hostname or "").lower().strip("[]")
    if not hostname:
        raise ValueError("Security Violation: Backend URL must contain a valid hostname.")

    # Block known cloud metadata endpoints and internal names
    blocked_hostnames = {
        "metadata.google.internal",
        "instance-data",
        "metadata",
        "169.254.169.254",
    }
    if hostname in blocked_hostnames:
        raise ValueError(f"Security Violation: Access to cloud metadata service ({hostname}) is strictly prohibited.")

    # DNS resolution and IP address validation for SSRF targets
    try:
        ip = ipaddress.ip_address(hostname)
        resolved_ips = [ip]
    except ValueError:
        resolved_ips = []
        try:
            addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
            for item in addr_info:
                resolved_ips.append(ipaddress.ip_address(item[4][0]))
        except Exception as exc:
            if not (os.environ.get("NOVA_TEST_MODE") and hostname in ("testclient", "testserver")):
                raise ValueError(f"Security Violation: Unable to resolve backend hostname '{hostname}': {exc}")
        if not resolved_ips and not (os.environ.get("NOVA_TEST_MODE") and hostname in ("testclient", "testserver")):
            raise ValueError(f"Security Violation: Hostname '{hostname}' did not resolve to a valid IP address.")

    for ip in resolved_ips:
        if str(ip) == "169.254.169.254" or ip in ipaddress.ip_network("169.254.0.0/16"):
            raise ValueError(f"Security Violation: Cloud metadata IP (169.254.0.0/16) on '{hostname}' is strictly prohibited.")
        if ip.is_link_local:
            raise ValueError(f"Security Violation: Link-local backend address '{hostname}' ({ip}) is not permitted.")
        if ip.is_multicast:
            raise ValueError(f"Security Violation: Multicast backend address '{hostname}' ({ip}) is not permitted.")
        if ip.is_reserved and not ip.is_loopback:
            raise ValueError(f"Security Violation: Reserved backend address '{hostname}' ({ip}) is not permitted.")

    return cleaned

_raw_backend = os.environ.get("NOVA_BACKEND_URL", os.environ.get("LLM_BACKEND_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")))
try:
    LLM_BACKEND_URL = validate_backend_url(_raw_backend)
except ValueError:
    if os.environ.get("NOVA_SAFE_FALLBACK", "0") == "1":
        LLM_BACKEND_URL = "http://127.0.0.1:11434"
    else:
        raise

OLLAMA_HOST = LLM_BACKEND_URL  # Backward compatibility alias

# Default Model & Limits
DEFAULT_MODEL = os.environ.get("NOVA_DEFAULT_MODEL", "nova:latest")
PARAM_LIMITS = {
    "num_ctx": (1024, 65536),
    "num_predict": (128, 8192),
    "temperature": (0.0, 1.5),
    "top_k": (1, 100),
    "top_p": (0.1, 1.0),
    "repeat_penalty": (0.8, 1.5),
}

# Terminal Execution Safety
WORKSPACE_DIR = Path(os.environ.get("NOVA_WORKSPACE", str(BASE_DIR))).resolve()
COMMAND_TIMEOUT_SECONDS = int(os.environ.get("NOVA_COMMAND_TIMEOUT", 30))

# Application Version & Update Channel (Opt-in for strict 100% offline localhost privacy)
VERSION = "2.1.0"
GITHUB_REPO = os.environ.get("NOVA_GITHUB_REPO", "ad4rshp/nova-console")
CHECK_UPDATES = os.environ.get("NOVA_CHECK_UPDATES", "0") in ("1", "true", "yes")

