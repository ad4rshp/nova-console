import os
import secrets

from fastapi import Request

from app.database import db_get_settings, db_set_setting

_CACHED_ADMIN_TOKEN: str | None = None

def get_or_create_admin_token() -> str:
    """
    Retrieves or generates the server administrative authorization token.
    Priority:
    1. NOVA_ADMIN_KEY or NOVA_API_KEY environment variable
    2. Persisted admin_auth_token in database settings
    3. Cryptographically generated 24-byte hex token saved to settings
    """
    global _CACHED_ADMIN_TOKEN
    env_key = os.environ.get("NOVA_ADMIN_KEY") or os.environ.get("NOVA_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    if _CACHED_ADMIN_TOKEN:
        return _CACHED_ADMIN_TOKEN

    try:
        settings = db_get_settings()
        stored_key = settings.get("admin_auth_token")
        if stored_key and isinstance(stored_key, str) and len(stored_key) >= 16:
            _CACHED_ADMIN_TOKEN = stored_key
            return _CACHED_ADMIN_TOKEN

        # Generate new cryptographically secure token
        new_token = secrets.token_hex(24)
        db_set_setting("admin_auth_token", new_token)
        _CACHED_ADMIN_TOKEN = new_token
        return _CACHED_ADMIN_TOKEN
    except Exception:
        # Fallback in-memory token if database is temporarily unavailable during early startup
        if not _CACHED_ADMIN_TOKEN:
            _CACHED_ADMIN_TOKEN = secrets.token_hex(24)
        return _CACHED_ADMIN_TOKEN

def rotate_admin_token() -> str:
    """
    Forces generation of a new administrative authorization token,
    updates persistent database settings, and invalidates in-memory cache.
    """
    global _CACHED_ADMIN_TOKEN
    new_token = secrets.token_hex(24)
    try:
        db_set_setting("admin_auth_token", new_token)
    except Exception:
        pass
    _CACHED_ADMIN_TOKEN = new_token
    return new_token

def verify_admin_token(provided_token: str | None) -> bool:
    """
    Performs constant-time comparison of the provided token against the server admin token.
    """
    if not provided_token or not isinstance(provided_token, str):
        return False
    expected = get_or_create_admin_token()
    return secrets.compare_digest(provided_token.strip(), expected.strip())

def extract_token_from_request(request: Request) -> str | None:
    """
    Extracts authorization token strictly from secure request headers.
    Supports:
    - Authorization: Bearer <token>
    - X-Nova-Auth: <token>
    
    Security note: Query parameters (?token=) are explicitly disallowed to prevent
    credential leakage in access logs, browser history, and Referer headers.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    x_nova_auth = request.headers.get("X-Nova-Auth", "")
    if x_nova_auth:
        return x_nova_auth.strip()

    return None

def is_request_authenticated(request: Request) -> bool:
    """
    Checks whether the incoming request contains a valid admin authorization token.
    """
    token = extract_token_from_request(request)
    return verify_admin_token(token)
