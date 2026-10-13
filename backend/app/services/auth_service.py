from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.database.mongodb import get_database
from app.schemas.user import UserRegister
from app.security.jwt import create_access_token
from app.security.password import hash_password, verify_password


async def register_user(user_data: UserRegister) -> str:
    db = get_database()
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user_doc = {
        "email": user_data.email,
        "hashed_password": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "role": user_data.role.value,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(user_doc)
    return str(result.inserted_id)


async def authenticate_user(email: str, password: str) -> dict:
    db = get_database()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return user


async def login_user(email: str, password: str) -> str:
    user = await authenticate_user(email, password)
    return create_access_token({"sub": str(user["_id"]), "email": user["email"], "role": user["role"]})
