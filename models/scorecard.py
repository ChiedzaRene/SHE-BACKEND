from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text, func
)
from sqlalchemy.orm import relationship
from database import Base


class Scorecard(Base):
    """
    Stores a scorecard submission for a site.
    Each submission has an overall_score (0–5 average across requirements)
    and an overall_percent (0–100).
    """
    __tablename__ = "scorecards"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    overall_score = Column(Float, nullable=False)       # 0.0 – 5.0
    overall_percent = Column(Float, nullable=False)     # 0.0 – 100.0
    notes = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=func.now(), nullable=False)

    site = relationship("Site", backref="scorecards")
    submitted_by_user = relationship("User", backref="scorecards")
    items = relationship("ScorecardItem", back_populates="scorecard", cascade="all, delete-orphan")


class ScorecardItem(Base):
    """
    Individual legal requirement score within a scorecard submission.
    Score is 0–5 per requirement.
    """
    __tablename__ = "scorecard_items"

    id = Column(Integer, primary_key=True, index=True)
    scorecard_id = Column(Integer, ForeignKey("scorecards.id"), nullable=False, index=True)
    requirement_ref = Column(String(100), nullable=False)   # e.g. "FWA-12", "EMA-05"
    requirement_text = Column(Text, nullable=True)
    score = Column(Float, nullable=False)                   # 0 – 5
    comments = Column(Text, nullable=True)

    scorecard = relationship("Scorecard", back_populates="items")