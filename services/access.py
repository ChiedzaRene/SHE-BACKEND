from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.site import Site
from models.user import User


def assert_site_access(user: User, site_id) -> None:
    """Site managers may only touch their own site; every other role may touch any site."""
    if user.role == "site_manager" and user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")


def region_site_ids(db: Session, user: User) -> Optional[List[int]]:
    """The sites a regional manager looks after (those in their region); None for everyone else."""
    if user.role != "regional_manager":
        return None
    if not user.region:
        return []
    return [sid for (sid,) in db.query(Site.id).filter(Site.region == user.region).all()]


def assert_site_visible(db: Session, user: User, site_id) -> None:
    """Like assert_site_access, and a regional manager only reaches the sites in their region."""
    assert_site_access(user, site_id)
    mine = region_site_ids(db, user)
    if mine is not None and site_id not in mine:
        raise HTTPException(status_code=403, detail="That site isn't in your region.")
