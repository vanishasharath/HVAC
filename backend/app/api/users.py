from fastapi import APIRouter, Body, Depends

from app.security.dependencies import require_admin
from app.services import user_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("")
async def list_users(current_user: dict = Depends(require_admin)):
    return {"success": True, "data": await user_service.list_users()}


@router.get("/{user_id}")
async def get_user(user_id: str, current_user: dict = Depends(require_admin)):
    return {"success": True, "data": await user_service.get_user(user_id)}


@router.put("/{user_id}")
async def update_user(user_id: str, update_data: dict = Body(...), current_user: dict = Depends(require_admin)):
    return {"success": True, "data": await user_service.update_user(user_id, update_data)}


@router.delete("/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(require_admin)):
    return {"success": True, "data": await user_service.delete_user(user_id)}
