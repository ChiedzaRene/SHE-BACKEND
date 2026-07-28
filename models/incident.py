from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)  # "injury", "spill", "fire", "environmental", "near-miss"
    description = Column(String, nullable=False)
    severity = Column(String, nullable=False)  # "low", "medium", "high", "critical"
    resolved = Column(Boolean, default=False)
    date_time = Column(DateTime, server_default=func.now())
    total_hours_worked = Column(Integer)
    lost_time_days = Column(Integer, default=0)
    occurred_at = Column(DateTime, nullable=True)
    


    # Relationships
    site = relationship("Site", back_populates="incidents")
    reported_by = relationship("User", back_populates="incidents")
    corrective_actions = relationship("CorrectiveAction", back_populates="incident")