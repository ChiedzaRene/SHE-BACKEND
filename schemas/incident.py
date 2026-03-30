from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class IncidentCreate(BaseModel):
    site_id: int
    type: str  # "injury", "spill", "fire", "environmental", "near-miss"
    description: str
    severity: str  # "low", "medium", "high", "critical"

class IncidentUpdate(BaseModel):
    type: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    resolved: Optional[bool] = None

class IncidentResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    type: str
    description: str
    severity: str
    resolved: bool
    date_time: Optional[datetime] = None

    class Config:
        from_attributes = True