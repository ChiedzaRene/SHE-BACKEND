from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    message: Optional[str] = None
    link: Optional[str] = None
    resource: Optional[str] = None
    resource_id: Optional[int] = None
    created_at: Optional[datetime] = None
    read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NotificationList(BaseModel):
    items: List[NotificationOut]
    unread: int


class MarkRead(BaseModel):
    # Mark these notifications read, or every unread one about a section (e.g. "incidents"), or all of them
    ids: Optional[List[int]] = Field(default=None, max_length=500)
    resource: Optional[str] = Field(default=None, max_length=40)
    all: bool = False
