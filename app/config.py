import os
import sys
from pathlib import Path

# Base Paths (Fully dynamic, supports standalone .exe / PyInstaller / Frozen mode)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BUNDLE_DIR = Path(sys._MEIPASS)
    BASE_DIR = Path(sys.executable).resolve().parent
    STATIC_DIR = BUNDLE_DIR
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    STATIC_DIR = BASE_DIR

DB_PATH = BASE_DIR / "nova-dashboard.db"
MODELFILE_PATH = BASE_DIR / "app" / "Modelfile"
if not MODELFILE_PATH.exists() and (BASE_DIR / "Modelfile").exists():
    MODELFILE_PATH = BASE_DIR / "Modelfile"
TEMPLATES_DIR = (BUNDLE_DIR if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else BASE_DIR) / "app" / "templates"

# Network & Service Configuration
# Security Rule: Default to 127.0.0.1 (Localhost Only).
# LAN exposure requires explicit opt-in via NOVA_ALLOW_LAN=1.
NOVA_ALLOW_LAN = os.environ.get("NOVA_ALLOW_LAN", "0").lower() in ("1", "true", "yes")

_env_host = os.environ.get("NOVA_HOST", "").strip()
if _env_host:
    if _env_host in ("0.0.0.0", "::") and not NOVA_ALLOW_LAN:
        # Prevent accidental LAN exposure unless explicitly permitted
        HOST = "127.0.0.1"
    else:
        HOST = _env_host
else:
    HOST = "0.0.0.0" if NOVA_ALLOW_LAN else "127.0.0.1"

try:
    PORT = int(os.environ.get("NOVA_PORT", os.environ.get("PORT", 8080)))
    if not (1 <= PORT <= 65535):
        PORT = 8080
except (ValueError, TypeError):
    PORT = 8080

# Universal Inference Engine (Ollama: 11434, LM Studio: 1234, vLLM: 8000, LocalAI: 8080, custom OpenAI endpoint)
LLM_BACKEND_URL = os.environ.get("NOVA_BACKEND_URL", os.environ.get("LLM_BACKEND_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))).rstrip("/")
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

# Application Version & Update Channel
VERSION = "2.1.0"
GITHUB_REPO = os.environ.get("NOVA_GITHUB_REPO", "ad4rshp/nova-console")
CHECK_UPDATES = os.environ.get("NOVA_CHECK_UPDATES", "1") == "1"

