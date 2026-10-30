import re
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    FACILITY_MANAGER = "FACILITY_MANAGER"
    TECHNICIAN = "TECHNICIAN"


E164_PHONE_REGEX = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone_number(v: str) -> str:
    if not isinstance(v, str):
        raise ValueError("Phone number must be a string")
    # Strip formatting characters: spaces, dashes, parentheses, dots
    cleaned = re.sub(r"[\s\(\)\-\.]", "", v.strip())
    if not cleaned.startswith("+"):
        raise ValueError("Phone number must include an international country code starting with '+' (e.g. +14155552671)")
    if not E164_PHONE_REGEX.match(cleaned):
        raise ValueError("Invalid phone number format. Must be a valid E.164 format with 8 to 15 digits (e.g. +14155552671)")
    return cleaned


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    phone_number: str
    role: UserRole = UserRole.TECHNICIAN

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_phone_number(v)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    phone_number: str | None = None
    phone_verified: bool = False
    role: UserRole
    created_at: datetime
