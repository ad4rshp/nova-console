import time
from typing import Any

import httpx

from app.config import CHECK_UPDATES, GITHUB_REPO, VERSION

_cached_update_result: dict[str, Any] | None = None
_last_check_time: float = 0.0
CACHE_DURATION_SECONDS = 3600 * 6  # 6 hours cache (zero background RAM consumption)

def parse_version(v_str: str) -> tuple[int, ...]:
    clean = v_str.lstrip("v").strip().split("-")[0]
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)

async def check_for_updates(force: bool = False) -> dict[str, Any]:
    global _cached_update_result, _last_check_time

    if not CHECK_UPDATES:
        return {"enabled": False, "current_version": VERSION, "has_update": False}

    now = time.time()
    if not force and _cached_update_result is not None and (now - _last_check_time < CACHE_DURATION_SECONDS):
        return _cached_update_result

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {"User-Agent": f"NovaConsole/{VERSION}"}

    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tag = data.get("tag_name", "").lstrip("v")
                latest_tuple = parse_version(tag)
                current_tuple = parse_version(VERSION)

                has_update = latest_tuple > current_tuple

                _cached_update_result = {
                    "enabled": True,
                    "current_version": VERSION,
                    "latest_version": tag or VERSION,
                    "has_update": has_update,
                    "release_name": data.get("name", f"Nova Console v{tag}"),
                    "release_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
                    "release_notes": (data.get("body") or "")[:600],
                    "published_at": data.get("published_at", ""),
                }
                _last_check_time = now
                return _cached_update_result
            elif resp.status_code in (403, 404):
                # Repo or release not yet published on GitHub, fallback gracefully
                _cached_update_result = {
                    "enabled": True,
                    "current_version": VERSION,
                    "latest_version": VERSION,
                    "has_update": False,
                    "message": "Up to date."
                }
                _last_check_time = now
                return _cached_update_result
    except Exception:
        pass

    # Graceful fallback when offline
    return {
        "enabled": True,
        "current_version": VERSION,
        "latest_version": VERSION,
        "has_update": False,
        "offline": True
    }

