from typing import Optional
import bleach
from pydantic import BaseModel, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from user-provided string inputs."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


class SiteCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    address: str = Field(..., min_length=3, max_length=255)
    latitude: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Latitude must be between -90 and 90 degrees",
    )
    longitude: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Longitude must be between -180 and 180 degrees",
    )
    contact_number: Optional[str] = Field(
        default=None,
        max_length=30,
        pattern=r"^\+?[0-9\s\-\(\)]+$",
        description="Valid phone number characters: digits, spaces, +, -, ()",
    )

    @field_validator("name", "address", "contact_number", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class SiteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    address: Optional[str] = Field(default=None, min_length=3, max_length=255)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    contact_number: Optional[str] = Field(
        default=None,
        max_length=30,
        pattern=r"^\+?[0-9\s\-\(\)]+$",
    )

    @field_validator("name", "address", "contact_number", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class SiteResponse(BaseModel):
    id: int
    name: str
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contact_number: Optional[str] = None

    class Config:
        from_attributes = True


SiteOut = SiteResponse