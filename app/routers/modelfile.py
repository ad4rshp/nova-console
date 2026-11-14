from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas import ModelfilePayload, UnloadPayload
from app.services.modelfile import (
    read_modelfile,
    rebuild_nova_model,
    update_modelfile,
)

router = APIRouter(tags=["modelfile"])

@router.get("/api/modelfile")
async def get_modelfile_endpoint():
    return read_modelfile()

@router.post("/api/modelfile")
async def update_modelfile_endpoint(payload: ModelfilePayload):
    try:
        return update_modelfile(payload.model_dump(exclude_unset=True))
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

@router.post("/api/rebuild-nova")
async def rebuild_nova_endpoint():
    res = await rebuild_nova_model(model_tag="nova")
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res)
    return res

@router.post("/api/unload")
async def unload_endpoint(payload: UnloadPayload):
    from app.services.providers.factory import get_async_provider
    provider = await get_async_provider()
    if not provider.capabilities.get("vram_eviction", False):
        return JSONResponse(
            status_code=501,
            content={"ok": False, "error": f"Model eviction is not supported by backend provider '{provider.name}'."}
        )
    success = await provider.unload_model(payload.model)
    if not success:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": f"Provider '{provider.name}' failed to unload model '{payload.model}'."}
        )
    return {"ok": True, "message": f"{payload.model} evicted from VRAM."}
