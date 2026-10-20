from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class SiteHoursUpsert(BaseModel):
    site_id: int = Field(..., gt=0)
    month: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")
    # 0 is allowed (site closed that month); the upper bound just catches typos
    hours_worked: float = Field(..., ge=0, le=1_000_000)
    # Number of people working at the site that month
    workers: Optional[int] = Field(default=None, ge=0, le=100_000)


class SiteHoursResponse(BaseModel):
    id: int
    site_id: int
    period: date
    hours_worked: float
    workers: Optional[int] = None
    entered_by: int
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
