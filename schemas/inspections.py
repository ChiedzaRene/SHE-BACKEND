from datetime import date, datetime
from typing import Optional
import bleach
from pydantic import BaseModel, Field, field_validator, ConfigDict


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from user-provided string inputs."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


class InspectionCreate(BaseModel):
    site_id: int = Field(..., gt=0, description="Site ID must be a positive integer")
    inspector_name: str = Field(..., min_length=2, max_length=150)
    inspection_date: date
    checklist_score: float = Field(0.0, ge=0.0, le=100.0)
    she_file_score: float = Field(0.0, ge=0.0, le=100.0)
    overall_score: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    comments: Optional[str] = Field(default="", max_length=2000)
    occurred_at: Optional[datetime] = None

    @field_validator("inspector_name", "comments", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class InspectionUpdate(BaseModel):
    inspector_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    inspection_date: Optional[date] = None
    checklist_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    she_file_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    overall_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    comments: Optional[str] = Field(default=None, max_length=2000)
    file_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("inspector_name", "comments", "file_url", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class InspectionResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    inspector_name: str
    inspection_date: date
    checklist_score: float
    she_file_score: float
    overall_score: float
    comments: Optional[str] = ""
    file_url: Optional[str] = None
    occurred_at: Optional[datetime] = None

    # Modern Pydantic V2 ORM mode setting:
    model_config = ConfigDict(from_attributes=True)