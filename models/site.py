from sqlalchemy import Column, Date, Integer, String, Float
from sqlalchemy.orm import relationship
from database import Base

class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    contact_number = Column(String, nullable=True)
    region = Column(String(100), nullable=True)  # e.g. Harare North, Bulawayo: groups sites for reporting
    # weekly toolbox talks are due from the first Monday on or after this date (empty: since tracking began)
    talks_from = Column(Date, nullable=True)

    # Relationships
    users = relationship("User", back_populates="site")
    incidents = relationship("Incident", back_populates="site")