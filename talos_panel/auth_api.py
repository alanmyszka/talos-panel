from fastapi import APIRouter, Request

from talos_panel.auth import require_user

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me")
async def current_identity(request: Request) -> dict:
    user = require_user(request)
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "csrf_token": request.state.csrf_token,
    }
