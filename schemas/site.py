from typing import Optional
import html
import bleach
from pydantic import BaseModel, Field, ValidationInfo, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from user-provided string inputs."""
    if isinstance(value, str):
        return html.unescape(bleach.clean(value, tags=[], strip=True)).strip()
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
    region: Optional[str] = Field(default=None, max_length=100)
    code: Optional[str] = Field(default=None, max_length=12, pattern=r"^[A-Za-z0-9-]*$",
                                description="Short code used in NC numbers, e.g. CBD")

    @field_validator("name", "address", "contact_number", "region", "code", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        value = sanitize_text(value)
        # The contact number is optional: a blank box means "no number", not an invalid one
        if info.field_name in ("contact_number", "region", "code") and value == "":
            return None
        if info.field_name == "code" and value:
            value = value.upper()
        if info.field_name == "region" and value:
            value = " ".join(value.split())
        return value


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
    region: Optional[str] = Field(default=None, max_length=100)
    code: Optional[str] = Field(default=None, max_length=12, pattern=r"^[A-Za-z0-9-]*$",
                                description="Short code used in NC numbers, e.g. CBD")

    @field_validator("name", "address", "contact_number", "region", "code", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        value = sanitize_text(value)
        # The contact number is optional: a blank box means "no number", not an invalid one
        if info.field_name in ("contact_number", "region", "code") and value == "":
            return None
        if info.field_name == "code" and value:
            value = value.upper()
        if info.field_name == "region" and value:
            value = " ".join(value.split())
        return value


class SiteResponse(BaseModel):
    id: int
    name: str
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contact_number: Optional[str] = None
    region: Optional[str] = None
    code: Optional[str] = None

    class Config:
        from_attributes = True


SiteOut = SiteResponse