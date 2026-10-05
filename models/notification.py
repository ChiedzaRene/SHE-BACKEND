from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from database import Base


class Notification(Base):
    """Something that happened which a particular person should know about."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)          # e.g. "incident_recorded", "action_assigned"
    title = Column(String(200), nullable=False)
    message = Column(String(500), nullable=True)
    link = Column(String(200), nullable=True)          # page in the app to open, e.g. "/incidents"
    resource = Column(String(40), nullable=True)       # "incidents", "corrective_actions", "audits", "users"
    resource_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
