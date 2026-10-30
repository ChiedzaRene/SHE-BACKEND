from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship

from models.corrective_action_file import CorrectiveActionFile
from sqlalchemy.sql import func
from database import Base

class CorrectiveAction(Base):
    __tablename__ = "corrective_actions"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    assigned_to = Column(String, nullable=False)
    action_taken = Column(String, nullable=False)
    designation = Column(String, default="Safety")
    priority = Column(String, default="medium")
    status = Column(String, default="open")
    due_date = Column(DateTime, nullable=True)
    date_resolved = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Resolution fields
    resolution_notes = Column(Text, nullable=True)
    resolved_by = Column(String, nullable=True)
    is_successful = Column(String, nullable=True)  # "yes" | "no"
    # set when the action was opened for an inspection non-conformity (managed from the inspection)
    nc_id = Column(Integer, nullable=True, index=True)
    # hierarchy of control from the incident form: elimination, substitution, isolation, redesign, administration, ppe
    control = Column(String(30), nullable=True)

    incident = relationship("Incident", back_populates="corrective_actions")
    _files = relationship(CorrectiveActionFile, order_by=CorrectiveActionFile.id, cascade="all, delete-orphan",
                          passive_deletes=True)