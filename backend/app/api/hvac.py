from fastapi import APIRouter, Depends

from app.schemas.hvac import HVACUnitCreate, HVACUnitUpdate
from app.security.dependencies import get_current_user, require_manager
from app.services import hvac_service

router = APIRouter(prefix="/api/v1/hvac", tags=["hvac"])


@router.post("", status_code=201)
async def create_hvac(data: HVACUnitCreate, current_user: dict = Depends(require_manager)):
    return {"success": True, "data": await hvac_service.create_hvac_unit(data)}


@router.get("")
async def list_hvac(current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": await hvac_service.list_hvac_units()}


@router.get("/{hvac_id}")
async def get_hvac(hvac_id: str, current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": await hvac_service.get_hvac_unit(hvac_id)}


@router.put("/{hvac_id}")
async def update_hvac(hvac_id: str, data: HVACUnitUpdate, current_user: dict = Depends(require_manager)):
    return {"success": True, "data": await hvac_service.update_hvac_unit(hvac_id, data)}


@router.delete("/{hvac_id}")
async def delete_hvac(hvac_id: str, current_user: dict = Depends(require_manager)):
    return {"success": True, "data": await hvac_service.delete_hvac_unit(hvac_id)}
