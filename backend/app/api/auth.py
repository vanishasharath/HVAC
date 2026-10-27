from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.schemas.auth import Token
from app.schemas.user import UserRegister
from app.security.dependencies import get_current_user
from app.services.auth_service import login_user, register_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(user_data: UserRegister):
    user_id = await register_user(user_data)
    return {"success": True, "user_id": user_id}


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    token = await login_user(form_data.username, form_data.password)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": str(current_user["_id"]),
        "email": current_user["email"],
        "full_name": current_user["full_name"],
        "role": current_user["role"],
    }
