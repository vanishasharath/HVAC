from fastapi import APIRouter, Depends

from app.schemas.sensor import SensorDataIn
from app.security.dependencies import verify_ingestion_key
from app.services.sensor_service import ingest_sensor_data

router = APIRouter(prefix="/api/v1", tags=["sensors"])


@router.post("/ingestion/sensor-data", status_code=201)
async def ingest_sensor_data_route(data: SensorDataIn, _authorized: bool = Depends(verify_ingestion_key)):
    """
    Real integration: every reading here is now run through the actual
    trained Isolation Forest / LSTM / Random Forest pipeline and evaluated
    for an alert - see app/services/sensor_service.py.
    """
    result = await ingest_sensor_data(data)
    return {"success": True, "data": result}
