import os
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

    # Respect strict 100% offline localhost privacy by default
    check_enabled = CHECK_UPDATES or os.environ.get("NOVA_CHECK_UPDATES", "0") in ("1", "true", "yes")
    if not check_enabled:
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
            elif resp.status_code == 404:
                # /releases/latest returns 404 if no GitHub Release has been drafted yet; query git tags as fallback
                tags_url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
                try:
                    tags_resp = await client.get(tags_url, headers=headers)
                    if tags_resp.status_code == 200:
                        tags_data = tags_resp.json()
                        if tags_data and isinstance(tags_data, list) and len(tags_data) > 0:
                            tag = tags_data[0].get("name", "").lstrip("v")
                            latest_tuple = parse_version(tag)
                            current_tuple = parse_version(VERSION)
                            has_update = latest_tuple > current_tuple
                            _cached_update_result = {
                                "enabled": True,
                                "current_version": VERSION,
                                "latest_version": tag or VERSION,
                                "has_update": has_update,
                                "release_name": f"Nova Console v{tag}",
                                "release_url": f"https://github.com/{GITHUB_REPO}/releases",
                                "release_notes": "",
                                "published_at": "",
                            }
                            _last_check_time = now
                            return _cached_update_result
                except Exception:
                    pass

                # Repo or release not yet published on GitHub, fallback cleanly without error
                _cached_update_result = {
                    "enabled": True,
                    "current_version": VERSION,
                    "latest_version": VERSION,
                    "has_update": False,
                    "message": "Up to date."
                }
                _last_check_time = now
                return _cached_update_result
            elif resp.status_code == 403:
                # GitHub API rate limited or forbidden
                _cached_update_result = {
                    "enabled": True,
                    "current_version": VERSION,
                    "latest_version": VERSION,
                    "has_update": False,
                    "message": "GitHub API rate limit exceeded."
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

