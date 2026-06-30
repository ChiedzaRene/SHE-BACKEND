from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Legal(Base):
    __tablename__ = "legal"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    requirements = Column(String, nullable=False)
    score = Column(Float, nullable=True)
    status = Column(String, default="compliant")  # "compliant", "non_compliant", "pending"
    expiry_date = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)
    date = Column(DateTime, server_default=func.now())

    site = relationship("Site")
    owner = relationship("User")