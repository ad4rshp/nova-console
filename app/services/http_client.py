import httpx

_SHARED_HTTP_CLIENT: httpx.AsyncClient | None = None

def get_shared_client() -> httpx.AsyncClient:
    """
    Returns a process-wide shared asynchronous HTTP client configured with
    connection pooling, standard keep-alive, and connection timeouts.
    """
    global _SHARED_HTTP_CLIENT
    if _SHARED_HTTP_CLIENT is None or _SHARED_HTTP_CLIENT.is_closed:
        _SHARED_HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0),
            follow_redirects=False,
        )
    return _SHARED_HTTP_CLIENT

async def close_shared_client() -> None:
    """
    Gracefully shuts down the shared HTTP client during application teardown.
    """
    global _SHARED_HTTP_CLIENT
    client = _SHARED_HTTP_CLIENT
    _SHARED_HTTP_CLIENT = None
    if client is not None and not client.is_closed:
        try:
            await client.aclose()
        except Exception:
            pass
