"""Who hears about what. Every notification is for one person; nobody is told about their own actions.

Notifying must never stop the action itself from saving, so failures are logged and swallowed.
"""
import logging
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.notification import Notification
from models.site import Site
from models.user import User

logger = logging.getLogger("she_portal")

TEAM_ROLES = ("super_admin", "admin", "she_team")


def team(db: Session) -> list:
    """Admins and the SHE team: they oversee every site."""
    return db.query(User).filter(User.role.in_(TEAM_ROLES), User.is_active.is_(True)).all()


def site_managers(db: Session, site_id: Optional[int]) -> list:
    if not site_id:
        return []
    return (
        db.query(User)
        .filter(User.role == "site_manager", User.site_id == site_id, User.is_active.is_(True))
        .all()
    )


def find_person(db: Session, name_or_email: Optional[str]) -> Optional[User]:
    """The account a free-text "assigned to" refers to: an email, or a full name that matches exactly one person."""
    text = (name_or_email or "").strip().lower()
    if not text:
        return None
    by_email = db.query(User).filter(func.lower(User.email) == text, User.is_active.is_(True)).first()
    if by_email:
        return by_email
    matches = db.query(User).filter(func.lower(func.trim(User.full_name)) == text, User.is_active.is_(True)).all()
    return matches[0] if len(matches) == 1 else None


def notify(
    db: Session,
    recipients: Iterable[User],
    *,
    kind: str,
    title: str,
    message: str = None,
    link: str = None,
    resource: str = None,
    resource_id: int = None,
    actor: Optional[User] = None,
) -> int:
    """Create one notification per recipient (each person once, never the person who acted)."""
    try:
        seen = set()
        for person in recipients:
            if person is None or person.id in seen or (actor is not None and person.id == actor.id):
                continue
            seen.add(person.id)
            db.add(Notification(
                user_id=person.id, kind=kind, title=title[:200], message=(message or "")[:500] or None,
                link=link, resource=resource, resource_id=resource_id,
            ))
        db.commit()
        return len(seen)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Could not create notifications (%s)", kind)
        return 0


def who(user: Optional[User]) -> str:
    if user is None:
        return "Someone"
    return user.full_name or user.email


def site_name(db: Session, site_id: Optional[int]) -> str:
    if not site_id:
        return "no site"
    row = db.query(Site.name).filter(Site.id == site_id).first()
    return row[0] if row else f"site #{site_id}"


def short(text: Optional[str], limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


ROLE_NAMES = {"super_admin": "Super admin", "admin": "Admin", "she_team": "SHE team", "site_manager": "Site manager"}


def account_changes(before: dict, user: User, db: Session) -> list:
    """Plain-English list of what an administrator changed on someone's account."""
    changes = []
    if before["role"] != user.role:
        changes.append(f"role is now {ROLE_NAMES.get(user.role, user.role)}")
    if before["site_id"] != user.site_id:
        changes.append(f"site is now {site_name(db, user.site_id) if user.site_id else 'all sites'}")
    if before["email"] != user.email:
        changes.append(f"sign-in email is now {user.email}")
    if before["full_name"] != user.full_name and user.full_name:
        changes.append(f"name is now {user.full_name}")
    return changes


def snapshot(user: User) -> dict:
    return {"role": user.role, "site_id": user.site_id, "email": user.email, "full_name": user.full_name}


def notify_account_update(db: Session, user: User, actor: User, before: dict, password_reset: bool) -> None:
    if password_reset:
        notify(db, [user], kind="password_reset", title="Your password was reset by an administrator",
               message=f"{who(actor)} set a temporary password for you, so you chose a new one at sign-in. "
                       "If you didn't ask for this, tell your administrator.",
               link="/settings", resource="users", resource_id=user.id, actor=actor)
    changes = account_changes(before, user, db)
    if changes:
        notify(db, [user], kind="account_updated", title="Your account was updated",
               message=f"{who(actor)} changed your account: " + "; ".join(changes) + ".",
               link="/settings", resource="users", resource_id=user.id, actor=actor)
