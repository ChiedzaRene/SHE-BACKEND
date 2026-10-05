from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.notification import Notification
from models.user import User
from schemas.notification import MarkRead, NotificationList
from services.auth_services import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])

# Opened notifications disappear this long after being opened (unread ones stay until read)
KEEP_AFTER_READING = timedelta(hours=24)


def _still_shown(now: datetime = None):
    """Unread, or opened less than 24 hours ago."""
    cutoff = (now or datetime.now(timezone.utc)) - KEEP_AFTER_READING
    return or_(Notification.read_at.is_(None), Notification.read_at >= cutoff)


@router.get("/", response_model=NotificationList)
def my_notifications(
    unread_only: bool = Query(False),
    resource: Optional[str] = Query(None, max_length=40),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The signed-in person's notifications, newest first, with how many are unread."""
    query = db.query(Notification).filter(Notification.user_id == current_user.id, _still_shown())
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


@router.post("/unread")
def mark_unread(
    payload: MarkRead,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Put notifications back to unread (only ones still shown: anything opened over 24 hours ago is gone)."""
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.read_at.isnot(None), _still_shown()
    )
    if payload.ids:
        query = query.filter(Notification.id.in_(payload.ids))
    elif payload.resource:
        query = query.filter(Notification.resource == payload.resource)
    elif not payload.all:
        return {"marked": 0}
    marked = query.update({Notification.read_at: None}, synchronize_session=False)
    db.commit()
    return {"marked": marked}
