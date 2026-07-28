from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from schemas.user import UserResponse, UserUpdate
from services.auth_services import require_role
from services.audit_service import log_action

router = APIRouter(prefix="/admin/users", tags=["Super Admin User Management"])


@router.get("/", response_model=List[UserResponse])
def list_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    """Retrieve all users across all sites."""
    return db.query(User).all()


@router.patch("/{user_id}", response_model=UserResponse)
def update_user_status_or_role(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    """Allows Super Admin to activate/deactivate users, change roles, or reassign sites."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_update.model_dump(exclude_unset=True)

    # Prevent deactivating yourself
    if user.id == current_user.id and update_data.get("is_active") is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    for key, value in update_data.items():
        if key == "password" and value:
            from services.auth_services import get_password_hash
            setattr(user, "password_hash", get_password_hash(value))
        else:
            setattr(user, key, value)

    db.commit()
    db.refresh(user)

    # Audit log entry
    log_action(
        db=db,
        user=current_user,
        action="UPDATE_USER",
        resource="users",
        resource_id=user.id,
        details=f"Updated user {user.email} (Role: {user.role}, Active: {user.is_active})"
    )

    return user