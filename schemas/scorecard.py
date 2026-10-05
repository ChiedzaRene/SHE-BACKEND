from datetime import datetime
from typing import List, Optional
import html
import bleach
from pydantic import BaseModel, EmailStr, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from user-provided string inputs."""
    if isinstance(value, str):
        return html.unescape(bleach.clean(value, tags=[], strip=True)).strip()
    return value


# ──────────────────────────────────────────────
# SITE schemas
# ──────────────────────────────────────────────

class SiteBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    location: Optional[str] = Field(default=None, max_length=255)

    @field_validator("name", "location", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class SiteCreate(SiteBase):
    pass


class SiteOut(SiteBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# USER schemas
# ──────────────────────────────────────────────

class UserBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    role: Optional[str] = Field(
        default="she_team",
        pattern="^(site_manager|she_team|admin|super_admin)$",
    )

    @field_validator("name", "role", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class UserCreate(UserBase):
    pass


class UserOut(UserBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# SCORECARD ITEM schemas
# ──────────────────────────────────────────────

class ScorecardItemCreate(BaseModel):
    requirement_ref: str = Field(..., min_length=1, max_length=100)
    requirement_text: Optional[str] = Field(default=None, max_length=1000)
    score: float = Field(..., ge=0.0, le=5.0, description="Item score between 0 and 5")
    comments: Optional[str] = Field(default=None, max_length=1500)

    @field_validator("requirement_ref", "requirement_text", "comments", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class ScorecardItemOut(ScorecardItemCreate):
    id: int
    scorecard_id: int

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# SCORECARD schemas
# ──────────────────────────────────────────────

class ScorecardCreate(BaseModel):
    site_id: int = Field(..., gt=0, description="Site ID must be a positive integer")
    # Ignored by the API (the authenticated user is always used); kept so older clients don't break
    submitted_by: Optional[int] = Field(default=None, gt=0)
    notes: Optional[str] = Field(default=None, max_length=2000)
    items: List[ScorecardItemCreate]

    @field_validator("notes", mode="before")
    @classmethod
    def clean_text_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class ScorecardOut(BaseModel):
    """
    Full scorecard with joined site_name and submitted_by_name.
    Matches the data structure consumed by ScorecardOverview.js.
    """

    id: int
    site_id: int
    site_name: Optional[str] = None
    submitted_by: int
    submitted_by_name: Optional[str] = None
    overall_score: float
    overall_percent: float
    notes: Optional[str] = None
    submitted_at: Optional[datetime] = None
    items: Optional[List[ScorecardItemOut]] = []

    class Config:
        from_attributes = True