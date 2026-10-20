from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import deferred
from sqlalchemy.sql import func

from database import Base


class SiteLicence(Base):
    """A licence a site must hold (council shop, fire brigade, EMA...), for one period.

    Recording the renewed licence adds a new row and marks the old one superseded, so the history stays.
    Reminders go to the site and the SHE team three months and one month before it is due, and when it expires.
    """

    __tablename__ = "site_licences"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    licence_type = Column(String(40), nullable=False, index=True)
    licence_number = Column(String(100), nullable=True)
    issue_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=False)             # when it expires / the renewal fee is due
    amount = Column(Float, nullable=True)                  # fee paid or due
    notes = Column(Text, nullable=True)
    document_name = Column(String(255), nullable=True)     # the licence certificate
    document_type = Column(String(120), nullable=True)
    document_size = Column(Integer, nullable=True)
    document = deferred(Column(LargeBinary, nullable=True))
    superseded_by = Column(Integer, ForeignKey("site_licences.id"), nullable=True)
    reminded_90 = Column(DateTime(timezone=True), nullable=True)
    reminded_30 = Column(DateTime(timezone=True), nullable=True)
    reminded_expired = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)
