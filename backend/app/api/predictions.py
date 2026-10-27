from fastapi import APIRouter, Depends

from app.security.dependencies import get_current_user
from app.services.prediction_service import predict_anomaly

router = APIRouter(prefix="/api/v1", tags=["ai"])


@router.get("/predict/{hvac_id}")
async def predict(hvac_id: str, current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": await predict_anomaly(hvac_id)}
