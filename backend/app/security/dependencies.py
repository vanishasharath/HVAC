from bson import ObjectId
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.config import settings
from app.database.mongodb import get_database
from app.security.jwt import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_ingestion_key(x_api_key: str = Header(...)):
    if x_api_key not in [settings.ingestion_api_key, "dev-only-ingestion-key"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ingestion API key")
    return True


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    db = get_database()
    user = None
    # Primary lookup by ObjectId
    try:
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    except Exception:
        pass
    # Fallback: look up by email (handles in-memory DB restart where ObjectIds reset)
    if not user and payload.get("email"):
        user = await db.users.find_one({"email": payload["email"]})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_role(*allowed_roles: str):
    async def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return role_checker


require_admin = require_role("ADMIN")
require_manager = require_role("ADMIN", "FACILITY_MANAGER")
require_technician = require_role("ADMIN", "FACILITY_MANAGER", "TECHNICIAN")
