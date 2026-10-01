from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.sql import func

from database import Base


class SiteHours(Base):
    """Total hours worked at a site in one calendar month (the TRIR/LTIFR denominator)."""

    __tablename__ = "site_hours"
    __table_args__ = (UniqueConstraint("site_id", "period", name="uq_site_hours_site_period"),)

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    period = Column(Date, nullable=False)  # always the first day of the month
    hours_worked = Column(Float, nullable=False)
    entered_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
