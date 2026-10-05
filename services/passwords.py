"""One place that decides what happens to sessions when a password changes."""
from sqlalchemy.orm import Session

from models.user import User
from services.auth_services import hash_password


def set_new_password(user: User, new_password: str, *, force_change: bool, revoke_sessions: bool) -> None:
    """Store a new password (caller commits).

    force_change    -> the user must pick their own password before using anything else
                       (used when an admin sets a temporary one)
    revoke_sessions -> every token issued so far stops working ("sign out everywhere")
    """
    user.password = hash_password(new_password)
    user.must_change_password = force_change
    if revoke_sessions:
        user.token_version = (user.token_version or 0) + 1


def reset_by_admin(db: Session, target: User, actor: User, new_password: str) -> bool:
    """An admin sets someone else's password. Returns True when it was a real reset.

    Resetting your *own* password from the Users page behaves like a normal change: no forced
    change (you just chose it) and your current session keeps working.
    """
    if target.id == actor.id:
        set_new_password(target, new_password, force_change=False, revoke_sessions=False)
        return False
    set_new_password(target, new_password, force_change=True, revoke_sessions=True)
    return True
