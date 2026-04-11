from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class LegalCreate(BaseModel):
    site_id: int
    requirements: str
    score: Optional[float] = None
    status: Optional[str] = "compliant"
    expiry_date: Optional[datetime] = None
    notes: Optional[str] = None

class LegalUpdate(BaseModel):
    requirements: Optional[str] = None
    score: Optional[float] = None
    status: Optional[str] = None
    expiry_date: Optional[datetime] = None
    notes: Optional[str] = None

class LegalResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    requirements: str
    score: Optional[float] = None
    status: str
    expiry_date: Optional[datetime] = None
    notes: Optional[str] = None
    date: Optional[datetime] = None

    class Config:
        from_attributes = True