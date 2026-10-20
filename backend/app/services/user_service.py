from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.database.mongodb import get_database


def _serialize(user: dict) -> dict:
    return {"id": str(user["_id"]), "email": user["email"], "full_name": user["full_name"], "role": user["role"]}


async def list_users() -> list:
    db = get_database()
    users = await db.users.find().to_list(length=200)
    return [_serialize(u) for u in users]


async def get_user(user_id: str) -> dict:
    db = get_database()
    try:
        oid = ObjectId(user_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id")
    user = await db.users.find_one({"_id": oid})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _serialize(user)


async def update_user(user_id: str, update_data: dict) -> dict:
    db = get_database()
    try:
        oid = ObjectId(user_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id")
    allowed = {"full_name", "role"}
    safe_update = {k: v for k, v in update_data.items() if k in allowed}
    result = await db.users.update_one({"_id": oid}, {"$set": safe_update})
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await get_user(user_id)


async def delete_user(user_id: str) -> dict:
    db = get_database()
    try:
        oid = ObjectId(user_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id")
    result = await db.users.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"success": True, "user_id": user_id}
