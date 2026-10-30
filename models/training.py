from sqlalchemy import Column, Integer, LargeBinary, String, ForeignKey, DateTime
from sqlalchemy.orm import deferred, relationship
from sqlalchemy.sql import func
from database import Base

class Training(Base):
    __tablename__ = "trainings"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    training_module = Column(String, nullable=False)
    personnel = Column(String, nullable=False)
    trainer_name = Column(String, nullable=True)
    trainer_position = Column(String, nullable=True)
    trained_employees = Column(Integer, default=0)
    total_employees = Column(Integer, default=0)
    date = Column(DateTime, server_default=func.now())
    type = Column(String, nullable=True)
    comments = Column(String, nullable=True)
    # supporting document (attendance register, certificate, slides...), kept in the database
    document_name = Column(String(255), nullable=True)
    document_type = Column(String(120), nullable=True)
    document_size = Column(Integer, nullable=True)
    document = deferred(Column(LargeBinary, nullable=True))
    # a training given online: the link to its recording (e.g. the OneDrive folder with the video)
    video_link = Column(String(1000), nullable=True)

    site = relationship("Site")
    trainer = relationship("User")