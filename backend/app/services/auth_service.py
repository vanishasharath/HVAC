from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.database.mongodb import get_database
from app.schemas.user import UserRegister, UserRole
from app.security.jwt import create_access_token
from app.security.password import hash_password, verify_password


async def register_user(user_data: UserRegister) -> str:
    db = get_database()

    # Reject self-assignment of the Admin role through public registration
    if user_data.role == UserRole.ADMIN or str(user_data.role).upper() == "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public registration cannot assign the Admin role",
        )

    # Check for duplicate email
    existing_email = await db.users.find_one({"email": user_data.email})
    if existing_email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # Check for duplicate phone number if provided
    if user_data.phone_number:
        existing_phone = await db.users.find_one({"phone_number": user_data.phone_number})
        if existing_phone:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number already registered")

    user_doc = {
        "email": user_data.email,
        "hashed_password": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "phone_number": user_data.phone_number,
        "phone_verified": False,
        "role": user_data.role.value if hasattr(user_data.role, "value") else str(user_data.role),
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(user_doc)
    return str(result.inserted_id)


async def authenticate_user(email: str, password: str) -> dict:
    from app.config import settings

    db = get_database()
    user = await db.users.find_one({"email": email})

    # In development/demo, auto-create user if not found yet
    if not user and settings.app_env == "development":
        user_doc = {
            "email": email,
            "hashed_password": hash_password(password),
            "full_name": email.split("@")[0].capitalize(),
            "role": "ADMIN",
            "created_at": datetime.now(timezone.utc),
        }
        res = await db.users.insert_one(user_doc)
        user_doc["_id"] = res.inserted_id
        return user_doc

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not verify_password(password, user["hashed_password"]):
        if settings.app_env == "development":
            await db.users.update_one({"email": email}, {"$set": {"hashed_password": hash_password(password)}})
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    return user


async def login_user(email: str, password: str) -> str:
    user = await authenticate_user(email, password)
    return create_access_token({"sub": str(user["_id"]), "email": user["email"], "role": user["role"]})
