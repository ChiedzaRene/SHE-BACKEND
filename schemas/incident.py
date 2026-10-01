from datetime import datetime
from datetime import timedelta
from typing import Optional
import bleach
from pydantic import BaseModel, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips HTML and script tags from text inputs to prevent XSS attacks."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


def check_not_future(value: Optional[datetime]) -> Optional[datetime]:
    # Clients send local wall-clock time (no timezone); a day of slack covers any UTC offset.
    if value is not None and value > datetime.utcnow() + timedelta(days=1):
        raise ValueError("occurred_at cannot be in the future")
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
    # When the incident actually happened; TRIR/LTIFR files it under this month
    occurred_at: Optional[datetime] = None

    @field_validator("type", "description", "severity", mode="before")
    @classmethod
    def clean_string_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)

    @field_validator("occurred_at")
    @classmethod
    def occurred_not_future(cls, value: Optional[datetime]) -> Optional[datetime]:
        return check_not_future(value)


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
    occurred_at: Optional[datetime] = None

    @field_validator("type", "description", "severity", mode="before")
    @classmethod
    def clean_string_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)

    @field_validator("occurred_at")
    @classmethod
    def occurred_not_future(cls, value: Optional[datetime]) -> Optional[datetime]:
        return check_not_future(value)


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
    occurred_at: Optional[datetime] = None

    class Config:
        from_attributes = True