from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, false
from sqlalchemy.orm import relationship

from database import Base


class IncidentWorkflow(Base):
    __tablename__ = "incident_workflows"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), unique=True, nullable=False)
    status = Column(String(40), nullable=False, default="reported", server_default="reported")
    investigation_team = Column(Text, nullable=True)
    # the form's tables: [{user_id, name, job_title, date}] (team members have accounts)
    # and [{action, control, by_whom, by_when}] (older records; corrective actions are now their own records)
    team_members = Column(JSON, nullable=True)
    action_items = Column(JSON, nullable=True)
    team_details = Column(Text, nullable=True)
    assignment_date = Column(DateTime, nullable=True)
    evidence = Column(Text, nullable=True)
    witness_reports = Column(Text, nullable=True)
    supporting_documents = Column(JSON, nullable=True)
    sketches = Column(Text, nullable=True)
    costs = Column(Text, nullable=True)
    damage_payer = Column(String(255), nullable=True)
    cost_usd = Column(Numeric(12, 2), nullable=True)
    causes = Column(JSON, nullable=True)
    root_cause = Column(Text, nullable=True)
    corrective_action = Column(Text, nullable=True)
    responsible_person = Column(String(255), nullable=True)
    due_date = Column(DateTime, nullable=True)
    lessons_learned = Column(Text, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    report_type = Column(String(60), nullable=True)
    # the form's REPORT TYPE box: {report type: date} for each ticked, and whether it revises an earlier report
    report_dates = Column(JSON, nullable=True)
    report_revised = Column(Boolean, nullable=False, default=False, server_default=false())
    she_comment = Column(Text, nullable=True)
    operations_manager_comment = Column(Text, nullable=True)

    incident = relationship("Incident", back_populates="_workflow")
    closed_by = relationship("User", foreign_keys=[closed_by_id])