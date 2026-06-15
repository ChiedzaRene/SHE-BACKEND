from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class ScorecardSubmission(Base):
    """
    One row per scorecard submission event for a site.
    Stores a cached overall_score (average of its items, out of 5)
    so it doesn't need to be recomputed on every read.
    """
    __tablename__ = "scorecard_submissions"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    overall_score = Column(Float, nullable=False)  # average out of 5
    submitted_at = Column(DateTime, server_default=func.now(), index=True)

    site = relationship("Site")
    submitter = relationship("User")
    items = relationship(
        "ScorecardItem",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="ScorecardItem.requirement_id",
    )


class ScorecardItem(Base):
    """
    One row per requirement score within a submission.
    requirement_id matches the frontend LEGAL_REQUIREMENT_DEFS ids
    (e.g. 'zera', 'ema', 'fire_brigade', ...).
    """
    __tablename__ = "scorecard_items"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(
        Integer, ForeignKey("scorecard_submissions.id"), nullable=False, index=True
    )
    requirement_id = Column(String, nullable=False)
    requirement_title = Column(String, nullable=False)
    score = Column(Float, nullable=False)  # 0-5

    submission = relationship("ScorecardSubmission", back_populates="items")