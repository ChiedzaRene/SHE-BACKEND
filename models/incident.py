from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, JSON
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
    # Who was hurt (injuries only). Kept as a name: the person may not have an account.
    injured_person = Column(String(150), nullable=True)
    # What will be done about it. The description is the record of what happened and can't be changed;
    # the action plan can be filled in and updated later.
    action_plan = Column(String, nullable=True)
    incident_intake = Column(JSON, nullable=False, default=dict, server_default="{}")
    


    # Relationships
    site = relationship("Site", back_populates="incidents")
    reported_by = relationship("User", back_populates="incidents")
    corrective_actions = relationship("CorrectiveAction", back_populates="incident")
    _workflow = relationship("IncidentWorkflow", back_populates="incident", uselist=False,
                              cascade="all, delete-orphan")
    _files = relationship("IncidentFile", order_by="IncidentFile.id", cascade="all, delete-orphan",
                          primaryjoin="Incident.id == foreign(IncidentFile.incident_id)")

    @property
    def files(self):
        """Evidence files (without their contents)."""
        from services.files import is_viewable
        return [{"id": f.id, "filename": f.filename, "content_type": f.content_type, "size": f.size,
                 "viewable": is_viewable(f.filename)} for f in self._files]

    @property
    def incident_workflow(self):
        if self._workflow is not None:
            return self._workflow
        return {"status": "reported"}