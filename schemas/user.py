from typing import Optional
import bleach
from pydantic import BaseModel, EmailStr, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from user-provided string inputs."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128, description="Password must be at least 8 characters long")
    full_name: Optional[str] = Field(default=None, max_length=150)
    role: str = Field(
        ...,
        pattern="^(site_manager|she_team|admin|super_admin)$",
        description="Role must be site_manager, she_team, admin, or super_admin",
    )
    site_id: Optional[int] = Field(default=None, gt=0)
    is_active: bool = True

    @field_validator("full_name", "role", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=150)
    role: Optional[str] = Field(
        default=None,
        pattern="^(site_manager|she_team|admin|super_admin)$",
    )
    site_id: Optional[int] = Field(default=None, gt=0)
    is_active: Optional[bool] = None

    @field_validator("full_name", "role", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class UserSelfUpdate(BaseModel):
    """What a user may change about themselves. Email and role are deliberately not here."""
    full_name: str = Field(..., min_length=1, max_length=150)

    @field_validator("full_name", mode="before")
    @classmethod
    def clean_name(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class ChangePassword(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str] = None
    role: str
    site_id: Optional[int] = None
    is_active: bool = True
    must_change_password: bool = False

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    role: Optional[str] = None
    user_id: Optional[int] = None
    site_id: Optional[int] = None
    full_name: Optional[str] = None