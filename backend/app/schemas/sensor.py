from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SensorReadings(BaseModel):
    """
    Raw sensor values - field names match RAW_COLS in
    app/ai/feature_engineering.py exactly, since these get fed directly
    into the real AI pipeline. Do not rename these without also updating
    the feature engineering / pipeline manager.
    """

    gas_ppm: Optional[float] = Field(default=None, ge=0)
    pressure: Optional[float] = Field(default=None, ge=0)
    temperature: Optional[float] = None
    humidity: Optional[float] = Field(default=None, ge=0, le=100)
    compressor_current: Optional[float] = Field(default=None, ge=0)

    # Not part of the AI feature vector - NDIR-specific refrigerant ppm,
    # kept as extra raw data. NDIR sensor model still TBD.
    refrigerant_ppm: Optional[float] = Field(default=None, ge=0)


class SensorDataIn(BaseModel):
    device_id: str
    hvac_id: str
    timestamp: datetime
    mode: str = "normal"
    event: Optional[str] = None
    sensors: SensorReadings
    edge_anomaly_score: Optional[float] = Field(default=None, ge=0, le=1)
    source: str = "unknown"
    schema_version: str = "1.0"


class SensorDataStoredOut(BaseModel):
    status: str
    device_id: str
    hvac_id: str
    timestamp: datetime
