from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class HVACUnitCreate(BaseModel):
    hvac_id: str
    name: str
    location: Optional[str] = None
    refrigerant_type: Optional[str] = "R-32"


class HVACUnitUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    refrigerant_type: Optional[str] = None


class HVACUnitOut(BaseModel):
    hvac_id: str
    name: str
    location: Optional[str] = None
    refrigerant_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime
