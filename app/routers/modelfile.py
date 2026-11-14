from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas import ModelfilePayload, UnloadPayload
from app.services.llm_engine import invalidate_model_cache
from app.services.modelfile import (
    read_modelfile,
    rebuild_nova_model,
    update_modelfile,
)
from app.services.rate_limiter import check_category_rate_limit

router = APIRouter(tags=["modelfile"])

@router.get("/api/modelfile")
async def get_modelfile_endpoint(request: Request):
    allowed, rl_headers, err = check_category_rate_limit(request, category="admin")
    if not allowed:
        return err
    return JSONResponse(content=read_modelfile(), headers=rl_headers)

@router.post("/api/modelfile")
async def update_modelfile_endpoint(payload: ModelfilePayload, request: Request):
    allowed, rl_headers, err = check_category_rate_limit(request, category="admin")
    if not allowed:
        return err
    try:
        res = update_modelfile(payload.model_dump(exclude_unset=True))
        return JSONResponse(content=res, headers=rl_headers)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)}, headers=rl_headers)

@router.post("/api/rebuild-nova")
async def rebuild_nova_endpoint(request: Request):
    allowed, rl_headers, err = check_category_rate_limit(request, category="admin")
    if not allowed:
        return err
    res = await rebuild_nova_model(model_tag="nova")
    invalidate_model_cache()
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res, headers=rl_headers)
    return JSONResponse(content=res, headers=rl_headers)

@router.post("/api/unload")
async def unload_endpoint(payload: UnloadPayload, request: Request):
    allowed, rl_headers, err = check_category_rate_limit(request, category="admin")
    if not allowed:
        return err
    from app.services.providers.factory import get_async_provider
    provider = await get_async_provider()
    if not provider.capabilities.get("vram_eviction", False):
        return JSONResponse(
            status_code=501,
            content={"ok": False, "error": f"Model eviction is not supported by backend provider '{provider.name}'."},
            headers=rl_headers
        )
    success = await provider.unload_model(payload.model)
    invalidate_model_cache()
    if not success:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": f"Provider '{provider.name}' failed to unload model '{payload.model}'."},
            headers=rl_headers
        )
    return JSONResponse(content={"ok": True, "message": f"{payload.model} evicted from VRAM."}, headers=rl_headers)
