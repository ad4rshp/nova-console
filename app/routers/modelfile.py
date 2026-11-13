from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas import ModelfilePayload, UnloadPayload
from app.services.modelfile import (
    evict_model_vram,
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
    return await rebuild_nova_model(model_tag="nova")

@router.post("/api/unload")
async def unload_endpoint(payload: UnloadPayload):
    try:
        await evict_model_vram(payload.model)
        return {"ok": True, "message": f"{payload.model} evicted from VRAM."}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
