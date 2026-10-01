from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from schemas.user import UserCreate, UserResponse, UserUpdate
from services.audit_service import log_action
from services.auth_services import get_current_user, hash_password, require_role

router = APIRouter(prefix="/users", tags=["Users"])


# Get all users (admin only)
@router.get("/", response_model=List[UserResponse])
def get_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    return db.query(User).all()


# Get current user profile
@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# Get specific user by ID (admin only)
@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Create new user (admin only)
@router.post("/", response_model=UserResponse)
def create_user(
    request: Request,
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    if user.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can create super admins")

    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=user.email,
        password=hash_password(user.password),
        full_name=user.full_name,
        role=user.role,
        site_id=user.site_id,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_action(
        db=db,
        user=current_user,
        action="CREATE_USER",
        resource="users",
        resource_id=new_user.id,
        details=f"Created user: {new_user.email} (Role: {new_user.role})",
        ip_address=request.client.host,
    )
    return new_user


# Update user (admin only)
@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    request: Request,
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if current_user.role != "super_admin" and (
        user.role == "super_admin" or user_data.role == "super_admin"
    ):
        raise HTTPException(status_code=403, detail="Only a super admin can modify super admins")

    if user_data.email is not None:
        existing_user = (
            db.query(User)
            .filter(User.email == user_data.email, User.id != user_id)
            .first()
        )
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = user_data.email

    if user_data.full_name is not None:
        user.full_name = user_data.full_name
    if user_data.role is not None:
        user.role = user_data.role
    if user_data.site_id is not None:
        user.site_id = user_data.site_id
    if user_data.is_active is not None:
        user.is_active = user_data.is_active
    if user_data.password:
        user.password = hash_password(user_data.password)

    db.commit()
    db.refresh(user)

    log_action(
        db=db,
        user=current_user,
        action="UPDATE_USER",
        resource="users",
        resource_id=user.id,
        details=f"Updated user #{user.id} ({user.email})",
        ip_address=request.client.host,
    )
    return user


# Delete user (admin only)
@router.delete("/{user_id}")
def delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if user.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can delete super admins")

    db.delete(user)
    db.commit()

    log_action(
        db=db,
        user=current_user,
        action="DELETE_USER",
        resource="users",
        resource_id=user_id,
        details=f"Deleted user #{user_id}",
        ip_address=request.client.host,
    )
    return {"message": "User deleted"}