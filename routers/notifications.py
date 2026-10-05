from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models.notification import Notification
from models.user import User
from schemas.notification import MarkRead, NotificationList
from services.auth_services import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=NotificationList)
def my_notifications(
    unread_only: bool = Query(False),
    resource: Optional[str] = Query(None, max_length=40),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The signed-in person's notifications, newest first, with how many are unread."""
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    if resource:
        query = query.filter(Notification.resource == resource)
    items = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .count()
    )
    return {"items": items, "unread": unread}


@router.post("/read")
def mark_read(
    payload: MarkRead,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.read_at.is_(None)
    )
    if payload.ids:
        query = query.filter(Notification.id.in_(payload.ids))
    elif payload.resource:
        query = query.filter(Notification.resource == payload.resource)
    elif not payload.all:
        return {"marked": 0}
    marked = query.update({Notification.read_at: datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    return {"marked": marked}
