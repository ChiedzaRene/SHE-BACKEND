from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import deferred
from sqlalchemy.sql import func

from database import Base


class SheFile(Base):
    """A document the SHE team or an admin shares with other roles.

    The file itself is kept in the database (not on the server's disk, which is wiped on every deploy).
    `view_only` is chosen by the uploader: others can open it in the app but not download it.
    """

    __tablename__ = "she_files"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False)
    size = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))  # only loaded when the file is opened
    view_only = Column(Boolean, nullable=False, default=False)
    # who it is for: comma-separated roles out of "site_manager", "she_team", "admin"
    audience = Column(String(100), nullable=False)
    # for site managers: one site only, or every site when empty
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
