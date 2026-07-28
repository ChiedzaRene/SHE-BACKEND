from datetime import datetime
from typing import Optional
import bleach
from pydantic import BaseModel, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips HTML and script tags from text inputs to prevent XSS attacks."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


class IncidentCreate(BaseModel):
    site_id: int = Field(..., gt=0, description="Site ID must be a positive integer")
    type: str = Field(..., min_length=2, max_length=100)
    description: str = Field(..., min_length=5, max_length=3000)
    severity: str = Field(
        ...,
        pattern="^(Low|Medium|High|Critical|low|medium|high|critical)$",
        description="Severity level must be Low, Medium, High, or Critical",
    )
    total_hours_worked: Optional[int] = Field(default=0, ge=0)
    lost_time_days: Optional[int] = Field(default=0, ge=0)

    @field_validator("type", "description", "severity", mode="before")
    @classmethod
    def clean_string_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class IncidentUpdate(BaseModel):
    type: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, min_length=5, max_length=3000)
    severity: Optional[str] = Field(
        default=None,
        pattern="^(Low|Medium|High|Critical|low|medium|high|critical)$",
    )
    resolved: Optional[bool] = None
    total_hours_worked: Optional[int] = Field(default=None, ge=0)
    lost_time_days: Optional[int] = Field(default=None, ge=0)

    @field_validator("type", "description", "severity", mode="before")
    @classmethod
    def clean_string_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class IncidentResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    type: str
    description: str
    severity: str
    resolved: bool
    date_time: Optional[datetime] = None
    total_hours_worked: Optional[int] = 0
    lost_time_days: Optional[int] = 0

    class Config:
        from_attributes = True