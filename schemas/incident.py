from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class IncidentUpdate(BaseModel):
    type: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    resolved: Optional[bool] = None
    total_hours_worked: Optional[int] = None
    lost_time_days: Optional[int] = None

class IncidentCreate(BaseModel):
    site_id: int
    type: str
    description: str
    severity: str
    total_hours_worked: Optional[int] = 0
    lost_time_days: Optional[int] = 0

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