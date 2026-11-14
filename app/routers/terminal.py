from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas import ExecuteCommandPayload, ProposeCommandPayload
from app.services.auth import extract_token_from_request, verify_admin_token
from app.services.terminal import generate_approval_token, run_system_command

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

@router.post("/propose")
async def propose_terminal_command(payload: ProposeCommandPayload):
    token_data = generate_approval_token(payload.command, working_dir=payload.working_dir)
    return token_data

@router.post("/execute")
async def execute_terminal_command(payload: ExecuteCommandPayload, request: Request):
    if not payload.approval_token:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "Execution declined: cryptographic server approval token required."}
        )

    user_auth = payload.user_authorization or extract_token_from_request(request)
    if not verify_admin_token(user_auth):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Execution declined: valid server-side user authorization credential required."}
        )

    result = run_system_command(
        payload.command,
        working_dir=payload.working_dir,
        approval_token=payload.approval_token,
        user_authorization=user_auth,
    )
    if not result.get("ok"):
        code = result.get("return_code", 403)
        status_code = code if code in (401, 403, 429, 503) else 400
        return JSONResponse(status_code=status_code, content=result)
    return result
