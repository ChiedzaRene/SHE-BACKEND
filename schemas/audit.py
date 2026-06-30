from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AuditCreate(BaseModel):
    site_id: int
    criteria: str
    score: float
    findings: Optional[str] = None
    status: Optional[str] = "open"

class AuditUpdate(BaseModel):
    criteria: Optional[str] = None
    score: Optional[float] = None
    findings: Optional[str] = None
    status: Optional[str] = None

class AuditResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    criteria: str
    score: float
    findings: Optional[str] = None
    status: str
    date: Optional[datetime] = None

    class Config:
        from_attributes = True