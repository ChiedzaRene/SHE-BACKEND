from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class CorrectiveAction(Base):
    __tablename__ = "corrective_actions"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=False)
    action_taken = Column(String, nullable=False)
    status = Column(String, default="open")  # "open", "in_progress", "resolved"
    due_date = Column(DateTime, nullable=True)
    date_resolved = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    incident = relationship("Incident", back_populates="corrective_actions")
    assignee = relationship("User")