from fastapi import APIRouter, Request

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
from app.services.updater import check_for_updates

router = APIRouter(tags=["dashboard"])

@router.get("/api/dashboard")
async def get_dashboard(request: Request):
    state = await get_dashboard_state()
    state["auth"] = {
        "lan_mode": NOVA_ALLOW_LAN,
        "is_authenticated": is_request_authenticated(request),
    }
    return state

@router.get("/api/check-update")
async def check_update_endpoint(force: bool = False):
    return await check_for_updates(force=force)

@router.get("/api/history")
async def get_history():
    return db_get_recent_requests(limit=100)

@router.get("/api/usage-summary")
async def get_usage_summary():
    return db_get_usage_summary()

@router.get("/api/settings")
async def get_settings_endpoint():
    return db_get_settings()

@router.post("/api/settings")
async def update_settings(payload: SettingsPayload):
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        if k in ALLOWED_SETTINGS:
            db_set_setting(k, v)
    return db_get_settings()
