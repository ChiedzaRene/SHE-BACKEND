from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime


# --- Input: a single requirement score ---
class ScorecardItemCreate(BaseModel):
    requirement_id: str
    requirement_title: str
    score: float = Field(ge=0, le=5)

    @field_validator("score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 2)


# --- Input: create a new submission for a site ---
class ScorecardSubmissionCreate(BaseModel):
    site_id: int
    items: List[ScorecardItemCreate]

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: List[ScorecardItemCreate]):
        if not v:
            raise ValueError("At least one scorecard item is required")
        return v


# --- Output: a single requirement score ---
class ScorecardItemResponse(BaseModel):
    id: int
    requirement_id: str
    requirement_title: str
    score: float

    class Config:
        from_attributes = True


# --- Output: a full submission ---
class ScorecardSubmissionResponse(BaseModel):
    id: int
    site_id: int
    submitted_by: int
    overall_score: float
    submitted_at: Optional[datetime] = None
    items: List[ScorecardItemResponse] = []

    class Config:
        from_attributes = True


# --- Output: condensed row for admin/SHE team list views ---
class ScorecardSummaryResponse(BaseModel):
    id: int
    site_id: int
    site_name: Optional[str] = None
    submitted_by: int
    submitted_by_name: Optional[str] = None
    overall_score: float
    overall_percent: int
    submitted_at: Optional[datetime] = None

    class Config:
        from_attributes = True