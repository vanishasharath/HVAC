from fastapi import APIRouter, Depends

from app.security.dependencies import get_current_user
from app.services.forecast_service import forecast_leak_probability

router = APIRouter(prefix="/api/v1", tags=["ai"])


@router.get("/forecast/{hvac_id}")
async def forecast(hvac_id: str, current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": await forecast_leak_probability(hvac_id)}
