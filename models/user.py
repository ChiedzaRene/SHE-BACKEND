from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, nullable=False)  # "admin", "she_team", "site_manager"
    is_active = Column(Boolean, default=True, server_default='true', nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    # Set when an admin creates the account or resets the password: the user must choose their own
    # password before the API lets them do anything else.
    must_change_password = Column(Boolean, default=False, server_default="false", nullable=False)
    # Bumped whenever the password changes. Tokens carry the value they were issued with, so every
    # older session stops working ("sign out everywhere").
    token_version = Column(Integer, default=0, server_default="0", nullable=False)

    # Relationships
    site = relationship("Site", back_populates="users")
    incidents = relationship("Incident", back_populates="reported_by")