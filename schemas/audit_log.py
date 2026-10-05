from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import html

import bleach

def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from outgoing text.

    bleach also turns & < > into &amp; &lt; &gt;. The page already escapes text when it shows it, so
    leaving those codes in would display "-&gt;" instead of "->"; turn them back into plain characters.
    """
    if isinstance(value, str):
        return html.unescape(bleach.clean(value, tags=[], strip=True)).strip()
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