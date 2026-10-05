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


class TrainingCreate(BaseModel):
    site_id: int = Field(..., gt=0, description="Site ID must be a positive integer")
    training_module: str = Field(..., min_length=2, max_length=200)
    personnel: str = Field(..., min_length=2, max_length=255)
    trainer_name: Optional[str] = Field(default=None, max_length=150)
    trainer_position: Optional[str] = Field(default=None, max_length=150)
    trained_employees: Optional[int] = Field(default=0, ge=0)
    total_employees: Optional[int] = Field(default=0, ge=0)
    type: Optional[str] = Field(default=None, max_length=100)
    comments: Optional[str] = Field(default=None, max_length=2000)

    @field_validator(
        "training_module",
        "personnel",
        "trainer_name",
        "trainer_position",
        "type",
        "comments",
        mode="before",
    )
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class TrainingUpdate(BaseModel):
    training_module: Optional[str] = Field(default=None, min_length=2, max_length=200)
    personnel: Optional[str] = Field(default=None, min_length=2, max_length=255)
    trainer_name: Optional[str] = Field(default=None, max_length=150)
    trainer_position: Optional[str] = Field(default=None, max_length=150)
    trained_employees: Optional[int] = Field(default=None, ge=0)
    total_employees: Optional[int] = Field(default=None, ge=0)
    type: Optional[str] = Field(default=None, max_length=100)
    comments: Optional[str] = Field(default=None, max_length=2000)

    @field_validator(
        "training_module",
        "personnel",
        "trainer_name",
        "trainer_position",
        "type",
        "comments",
        mode="before",
    )
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class TrainingResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    training_module: str
    personnel: str
    trainer_name: Optional[str] = None
    trainer_position: Optional[str] = None
    trained_employees: int
    total_employees: int
    date: Optional[datetime] = None
    type: Optional[str] = None
    comments: Optional[str] = None

    class Config:
        from_attributes = True