from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from database import get_db
from models.user import User
from schemas.user import UserCreate, UserResponse, Token
from services.auth_services import (
    require_role,
    hash_password,
    authenticate_user,
    create_access_token,
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
        site_id=user_data.site_id
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
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

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled. Contact your administrator."
        )

    access_token = create_access_token(data={
        "sub": user.email,
        "role": user.role,
        "user_id": user.id,
        "site_id": user.site_id
    })

    return {"access_token": access_token, "token_type": "bearer"}