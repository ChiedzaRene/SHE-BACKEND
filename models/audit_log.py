from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, nullable=False)
    user_role = Column(String, nullable=False)
    action = Column(String, nullable=False)      # e.g. "CREATE_INCIDENT"
    resource = Column(String, nullable=False)    # e.g. "incidents"
    resource_id = Column(Integer, nullable=True) # e.g. incident id
    details = Column(Text, nullable=True)        # extra info
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())