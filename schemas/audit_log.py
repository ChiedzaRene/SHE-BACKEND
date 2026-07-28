from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import bleach

def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from incoming or outgoing string data."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


class AuditLogResponse(BaseModel):
    id: int
    user_email: str
    user_role: str
    action: str
    resource: str
    resource_id: Optional[int] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    timestamp: datetime

    # Sanitize string fields automatically
    @field_validator("user_email", "user_role", "action", "resource", "details", "ip_address", mode="before")
    @classmethod
    def sanitize_fields(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)

    class Config:
        from_attributes = True