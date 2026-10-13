from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.database.mongodb import get_database
from app.schemas.hvac import HVACUnitCreate, HVACUnitUpdate


async def create_hvac_unit(data: HVACUnitCreate) -> dict:
    db = get_database()
    existing = await db.hvac_units.find_one({"hvac_id": data.hvac_id})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="HVAC unit already exists")
    now = datetime.now(timezone.utc)
    doc = data.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now
    await db.hvac_units.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_hvac_units() -> list:
    db = get_database()
    units = await db.hvac_units.find().to_list(length=200)
    for u in units:
        u["_id"] = str(u["_id"])
    return units


async def get_hvac_unit(hvac_id: str) -> dict:
    db = get_database()
    unit = await db.hvac_units.find_one({"hvac_id": hvac_id})
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HVAC unit not found")
    unit["_id"] = str(unit["_id"])
    return unit


async def update_hvac_unit(hvac_id: str, update_data: HVACUnitUpdate) -> dict:
    db = get_database()
    update_dict = update_data.model_dump(exclude_none=True)
    update_dict["updated_at"] = datetime.now(timezone.utc)
    result = await db.hvac_units.update_one({"hvac_id": hvac_id}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HVAC unit not found")
    return await get_hvac_unit(hvac_id)


async def delete_hvac_unit(hvac_id: str) -> dict:
    db = get_database()
    result = await db.hvac_units.delete_one({"hvac_id": hvac_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HVAC unit not found")
    return {"success": True, "hvac_id": hvac_id}
