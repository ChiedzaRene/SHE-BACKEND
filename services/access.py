from fastapi import HTTPException

from models.user import User


def assert_site_access(user: User, site_id) -> None:
    """Site managers may only touch their own site; every other role may touch any site."""
    if user.role == "site_manager" and user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
