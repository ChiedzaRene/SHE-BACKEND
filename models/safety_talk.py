from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import deferred
from sqlalchemy.sql import func

from database import Base


class SafetyTalk(Base):
    """The weekly toolbox talk a site manager gives on Monday, with its supporting document.

    One per site per week. It can be submitted from Monday until the end of Tuesday (local time).
    """

    __tablename__ = "safety_talks"
    __table_args__ = (UniqueConstraint("site_id", "week_of", name="uq_safety_talk_site_week"),)

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    week_of = Column(Date, nullable=False, index=True)        # the Monday of the talk's week
    title = Column(String(200), nullable=False)
    attendees = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False)
    size = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)


class SafetyTalkMiss(Base):
    """A week whose submission window closed without a talk: recorded once, when the SHE team is told."""

    __tablename__ = "safety_talk_misses"
    __table_args__ = (UniqueConstraint("site_id", "week_of", name="uq_safety_talk_miss_site_week"),)

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    week_of = Column(Date, nullable=False)
    notified_at = Column(DateTime(timezone=True), server_default=func.now())
