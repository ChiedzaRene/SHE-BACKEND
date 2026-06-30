from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# ──────────────────────────────────────────────
# SITE schemas
# ──────────────────────────────────────────────

class SiteBase(BaseModel):
    name: str
    location: Optional[str] = None


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
    name: str
    email: str
    role: Optional[str] = "she_team"


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
    requirement_ref: str
    requirement_text: Optional[str] = None
    score: float = Field(..., ge=0, le=5)
    comments: Optional[str] = None


class ScorecardItemOut(ScorecardItemCreate):
    id: int
    scorecard_id: int

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# SCORECARD schemas
# ──────────────────────────────────────────────

class ScorecardCreate(BaseModel):
    site_id: int
    submitted_by: int
    notes: Optional[str] = None
    items: List[ScorecardItemCreate]


class ScorecardOut(BaseModel):
    """
    Full scorecard with joined site_name and submitted_by_name.
    This is exactly what ScorecardOverview.js expects.
    """
    id: int
    site_id: int
    site_name: Optional[str] = None         # joined from sites.name
    submitted_by: int
    submitted_by_name: Optional[str] = None  # joined from users.name
    overall_score: float
    overall_percent: float
    notes: Optional[str] = None
    submitted_at: Optional[datetime] = None
    items: Optional[List[ScorecardItemOut]] = []

    class Config:
        from_attributes = True