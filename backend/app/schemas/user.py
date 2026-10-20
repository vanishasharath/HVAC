from datetime import datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    FACILITY_MANAGER = "FACILITY_MANAGER"
    TECHNICIAN = "TECHNICIAN"


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: UserRole = UserRole.TECHNICIAN


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    created_at: datetime
