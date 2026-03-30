from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin", "she_team", "site_manager"
    is_active = Column(Boolean, default=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    # Relationships
    site = relationship("Site", back_populates="users")
    incidents = relationship("Incident", back_populates="reported_by")