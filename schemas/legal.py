from datetime import datetime
from typing import Optional
import html
import bleach
from pydantic import BaseModel, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from user-provided string inputs."""
    if isinstance(value, str):
        return html.unescape(bleach.clean(value, tags=[], strip=True)).strip()
    return value


class LegalCreate(BaseModel):
    site_id: int = Field(..., gt=0, description="Site ID must be a positive integer")
    requirements: str = Field(..., min_length=3, max_length=1000)
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    status: Optional[str] = Field(
        default="compliant",
        pattern="^(compliant|non_compliant|pending_review|expired)$",
    )
    expiry_date: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("requirements", "status", "notes", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class LegalUpdate(BaseModel):
    requirements: Optional[str] = Field(default=None, min_length=3, max_length=1000)
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    status: Optional[str] = Field(
        default=None,
        pattern="^(compliant|non_compliant|pending_review|expired)$",
    )
    expiry_date: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("requirements", "status", "notes", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class LegalResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    requirements: str
    score: Optional[float] = None
    status: str
    expiry_date: Optional[datetime] = None
    notes: Optional[str] = None
    date: Optional[datetime] = None

    class Config:
        from_attributes = True