from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import deferred, relationship
from sqlalchemy.sql import func

from database import Base


class FireInspection(Base):
    """A site's own check of its fire equipment.

    kind "fortnightly": the fortnightly fire equipment checklist (GP-SHE/OPR/10/02), every item answered.
    kind "service_refill": the six-monthly service and refill of the fire extinguishers, with the
    contractor's proof. The next one is due six months later; the SHE team is told two weeks before.
    """

    __tablename__ = "fire_inspections"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    inspection_date = Column(Date, nullable=False)
    inspector_name = Column(String(150), nullable=False)
    contractor = Column(String(200), nullable=True)                  # service company (service_refill)
    extinguishers = Column(Integer, nullable=True)                   # how many were serviced (service_refill)
    answers = Column(JSON, nullable=False, default=dict)             # item key -> {"result": C|NC|NA, "comment"}
    comments = Column(Text, nullable=True)
    next_due = Column(Date, nullable=False)
    reminded_at = Column(DateTime(timezone=True), nullable=True)     # the two-week reminder was sent
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    files = relationship("FireInspectionFile", back_populates="inspection", cascade="all, delete-orphan",
                         passive_deletes=True, order_by="FireInspectionFile.id")


class FireInspectionFile(Base):
    """Proof sent with a fire equipment inspection: photos, the service certificate, the signed form."""

    __tablename__ = "fire_inspection_files"

    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("fire_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False)
    size = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    inspection = relationship("FireInspection", back_populates="files")
