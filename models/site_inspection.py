from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import deferred, relationship
from sqlalchemy.sql import func

from database import Base


class SiteInspection(Base):
    """An inspection report written by the SHE team: formatted heading sections and its non-conformities.

    Status: draft (being written) -> submitted (NCs sent to the regional office) -> closed (every NC closed).
    """

    __tablename__ = "site_inspections"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, nullable=False, unique=True)            # report number, e.g. 15
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    inspection_date = Column(Date, nullable=False)
    inspectors = Column(String(300), nullable=True)
    # formatted text (cleaned HTML: bold, italic, underline, lists)
    introduction = Column(Text, nullable=True)
    criteria = Column(Text, nullable=True)
    objectives = Column(Text, nullable=True)
    findings_summary = Column(Text, nullable=True)                   # overall observations
    conformities = Column(Text, nullable=True)                       # positive observations
    status = Column(String(20), nullable=False, default="draft")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    ncs = relationship("InspectionNC", back_populates="inspection", order_by="InspectionNC.seq",
                       cascade="all, delete-orphan")
    # proof of the inspection itself: photos, the signed checklist, other documents
    attachments = relationship("InspectionPhoto", back_populates="inspection", cascade="all, delete-orphan",
                               order_by="InspectionPhoto.id")


class InspectionNC(Base):
    """A non-conformity (or negative observation) raised in an inspection, and its corrective action.

    Status: draft -> raised (with the regional office) -> assigned (acknowledged, action opened, deadline set)
            -> completed (the responsible person says how it was closed) -> closed (verified by the SHE team),
            or back to assigned when the SHE team finds it isn't done.
    """

    __tablename__ = "inspection_ncs"
    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("site_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    serial = Column(String(40), nullable=False, unique=True)         # e.g. 15/CBD/01
    title = Column(String(200), nullable=False)
    details = Column(Text, nullable=True)                            # formatted text
    reference = Column(String(500), nullable=True)                   # standard / clause breached
    status = Column(String(20), nullable=False, default="draft")
    # regional office: acknowledgement, recommended corrective action, who and by when
    recommendation = Column(Text, nullable=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    due_date = Column(Date, nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    corrective_action_id = Column(Integer, ForeignKey("corrective_actions.id"), nullable=True)
    # the person responsible: how it was closed
    completion_notes = Column(Text, nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # SHE team verification
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by_name = Column(String(150), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_outcome = Column(String(20), nullable=True)               # "closed" | "open"
    review_comment = Column(Text, nullable=True)

    inspection = relationship("SiteInspection", back_populates="ncs")
    photos = relationship("InspectionPhoto", back_populates="nc", cascade="all, delete-orphan",
                          order_by="InspectionPhoto.id")


class InspectionPhoto(Base):
    """A photo or document kept as proof.

    kind: "report" (proof of the inspection, attached to the report), "finding" (proof of an NC),
    "evidence" (proof that the NC's corrective action was done).
    """

    __tablename__ = "inspection_photos"

    id = Column(Integer, primary_key=True, index=True)
    nc_id = Column(Integer, ForeignKey("inspection_ncs.id", ondelete="CASCADE"), nullable=True, index=True)
    inspection_id = Column(Integer, ForeignKey("site_inspections.id", ondelete="CASCADE"), nullable=True, index=True)
    kind = Column(String(20), nullable=False, default="finding")
    filename = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False)
    size = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    nc = relationship("InspectionNC", back_populates="photos")
    inspection = relationship("SiteInspection", back_populates="attachments")
