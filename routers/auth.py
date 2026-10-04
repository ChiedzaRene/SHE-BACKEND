from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from database import get_db
from models.user import User
from schemas.user import ChangePassword, UserCreate, UserResponse, Token
from services.audit_service import log_action, log_event
from services.passwords import set_new_password
from services.auth_services import (
    get_current_user,
    verify_password,
    require_role,
    hash_password,
    authenticate_user,
    issue_token,
    get_user_by_email
)

# Rate limiter — keyed by IP address
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse)
@limiter.limit("3/minute")  # max 3 registrations per minute per IP
def register(
    request: Request,
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    # Registration is staff-only: self-service sign-up would let anyone pick their own role.
    if user_data.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can create super admins")

    existing_user = db.query(User).filter(
        User.email == user_data.email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    new_user = User(
        email=user_data.email,
        password=hash_password(user_data.password),
        full_name=user_data.full_name,
        role=user_data.role,
        site_id=user_data.site_id,
        must_change_password=True,  # an admin chose this password, so the user picks their own at first sign-in
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
        ip_address=request.client.host if request.client else None,
    )
    return new_user


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")  # max 5 login attempts per minute per IP
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # OAuth2PasswordRequestForm uses "username" field — we treat it as email
    user = authenticate_user(db, form_data.username, form_data.password)
    ip = request.client.host if request.client else None

    if not user:
        # Recorded so an admin can see someone guessing a password. The typed password is never stored.
        known = get_user_by_email(db, form_data.username)
        log_event(
            db,
            email=form_data.username,
            role=known.role if known else "unknown",
            action="LOGIN_FAILED",
            resource="auth",
            details="Wrong password" if known else "No account with this email",
            ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        log_action(db=db, user=user, action="LOGIN_FAILED", resource="auth",
                   details="Account is deactivated", ip_address=ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled. Contact your administrator."
        )

    log_action(db=db, user=user, action="LOGIN", resource="auth", details="Signed in", ip_address=ip)
    return {"access_token": issue_token(user), "token_type": "bearer"}


@router.post("/change-password")
@limiter.limit("5/minute")  # guessing the current password is the only thing this endpoint can be abused for
def change_password(
    request: Request,
    payload: ChangePassword,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 400, not 401: the frontend signs the user out on any 401
    if not verify_password(payload.current_password, current_user.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")

    # Every other session is signed out; the caller gets a fresh token below so this one continues
    set_new_password(current_user, payload.new_password, force_change=False, revoke_sessions=True)
    db.commit()
    log_action(
        db=db,
        user=current_user,
        action="CHANGE_PASSWORD",
        resource="users",
        resource_id=current_user.id,
        details="User changed their own password; all other sessions were signed out",
        ip_address=request.client.host if request.client else None,
    )
    return {"message": "Password changed", "access_token": issue_token(current_user), "token_type": "bearer"}
