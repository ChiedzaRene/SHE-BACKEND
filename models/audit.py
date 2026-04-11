from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Audit(Base):
    __tablename__ = "audits"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    criteria = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    findings = Column(String, nullable=True)
    status = Column(String, default="open")  # "open", "closed", "action_required"
    date = Column(DateTime, server_default=func.now())

    site = relationship("Site")
    auditor = relationship("User")