from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.schemas.alert import AlertResolveRequest
from app.security.dependencies import get_current_user, require_technician
from app.services.alert_service import get_alert, list_alerts, resolve_alert

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("")
async def get_alerts(
    hvac_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    return {"success": True, "data": await list_alerts(hvac_id=hvac_id, status_filter=status)}


@router.get("/{alert_id}")
async def get_single_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": await get_alert(alert_id)}


@router.put("/{alert_id}/resolve")
async def resolve_single_alert(
    alert_id: str, body: AlertResolveRequest, current_user: dict = Depends(require_technician)
):
    result = await resolve_alert(alert_id, resolved_by=str(current_user["_id"]), resolution_note=body.resolution_note)
    return {"success": True, "data": result}
