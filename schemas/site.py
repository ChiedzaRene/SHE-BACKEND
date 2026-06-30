from pydantic import BaseModel
from typing import Optional

class SiteCreate(BaseModel):
    name: str
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contact_number: Optional[str] = None

class SiteUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contact_number: Optional[str] = None

class SiteResponse(BaseModel):
    id: int
    name: str
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contact_number: Optional[str] = None

    class Config:
<<<<<<< HEAD
        from_attributes = True


SiteOut = SiteResponse
=======
        from_attributes = True
>>>>>>> 1407a1a5ec06c717d7b3708ad7ea653135048d5d
