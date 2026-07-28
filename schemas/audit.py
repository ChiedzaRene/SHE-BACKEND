from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import bleach


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips HTML and script tags from text inputs to prevent XSS attacks."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


class AuditCreate(BaseModel):
    site_id: int = Field(..., gt=0, description="Site ID must be a positive integer")
    criteria: str = Field(..., min_length=2, max_length=255)
    score: float = Field(..., ge=0.0, le=100.0, description="Score must be between 0 and 100")
    findings: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = Field("open", pattern="^(open|in_progress|completed|closed)$")

    @field_validator("criteria", "findings", "status", mode="before")
    @classmethod
    def clean_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class AuditUpdate(BaseModel):
    criteria: Optional[str] = Field(None, min_length=2, max_length=255)
    score: Optional[float] = Field(None, ge=0.0, le=100.0)
    findings: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = Field(None, pattern="^(open|in_progress|completed|closed)$")

    @field_validator("criteria", "findings", "status", mode="before")
    @classmethod
    def clean_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class AuditResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    criteria: str
    score: float
    findings: Optional[str] = None
    status: str
    date: Optional[datetime] = None

    class Config:
        from_attributes = True