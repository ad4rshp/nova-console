from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import NOVA_ALLOW_LAN
from app.database import (
    db_get_recent_requests,
    db_get_settings,
    db_get_usage_summary,
    db_set_setting,
)
from app.schemas import ALLOWED_SETTINGS, SettingsPayload
from app.services.auth import is_request_authenticated
from app.services.llm_engine import get_dashboard_state
from app.services.rate_limiter import check_category_rate_limit
from app.services.updater import check_for_updates

router = APIRouter(tags=["dashboard"])

@router.get("/api/dashboard")
async def get_dashboard(request: Request, refresh: bool = False):
    allowed, rl_headers, err = check_category_rate_limit(request, category="dashboard")
    if not allowed:
        return err

    state = await get_dashboard_state(force_refresh=refresh)
    state["auth"] = {
        "lan_mode": NOVA_ALLOW_LAN,
        "is_authenticated": is_request_authenticated(request),
    }
    return JSONResponse(content=state, headers=rl_headers)

@router.get("/api/check-update")
async def check_update_endpoint(force: bool = False):
    return await check_for_updates(force=force)

@router.get("/api/history")
async def get_history(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    model: str | None = None
):
    allowed, rl_headers, err = check_category_rate_limit(request, category="history")
    if not allowed:
        return err

    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    records = db_get_recent_requests(limit=safe_limit, offset=safe_offset, model=model)
    return JSONResponse(content=records, headers=rl_headers)

@router.get("/api/usage-summary")
async def get_usage_summary(request: Request):
    allowed, rl_headers, err = check_category_rate_limit(request, category="dashboard")
    if not allowed:
        return err
    return JSONResponse(content=db_get_usage_summary(), headers=rl_headers)

@router.get("/api/settings")
async def get_settings_endpoint(request: Request):
    allowed, rl_headers, err = check_category_rate_limit(request, category="settings")
    if not allowed:
        return err
    return JSONResponse(content=db_get_settings(), headers=rl_headers)

@router.post("/api/settings")
async def update_settings(payload: SettingsPayload, request: Request):
    allowed, rl_headers, err = check_category_rate_limit(request, category="settings")
    if not allowed:
        return err

    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        if k in ALLOWED_SETTINGS:
            db_set_setting(k, v)
    return JSONResponse(content=db_get_settings(), headers=rl_headers)
