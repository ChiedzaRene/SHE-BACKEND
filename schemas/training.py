from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TrainingCreate(BaseModel):
    site_id: int
    training_module: str
    personnel: str
    trainer_name: Optional[str] = None
    trainer_position: Optional[str] = None
    trained_employees: Optional[int] = 0
    total_employees: Optional[int] = 0
    type: Optional[str] = None
    comments: Optional[str] = None

class TrainingUpdate(BaseModel):
    training_module: Optional[str] = None
    personnel: Optional[str] = None
    trainer_name: Optional[str] = None
    trainer_position: Optional[str] = None
    trained_employees: Optional[int] = None
    total_employees: Optional[int] = None
    type: Optional[str] = None
    comments: Optional[str] = None

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