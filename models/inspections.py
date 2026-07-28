from sqlalchemy import Column, Integer, Float, String, Text, Date, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    inspector_name = Column(String, nullable=False)
    inspection_date = Column(Date, nullable=False)
    checklist_score = Column(Float, nullable=False)   # 0-100
    she_file_score = Column(Float, nullable=False)    # 0-100
    overall_score = Column(Float, nullable=False)     # avg of above two
    comments = Column(Text, default="")
    file_url = Column(String, nullable=True)          # NEW: Stores uploaded file path/URL
    created_at = Column(DateTime(timezone=True), server_default=func.now())