import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from models.user import User
from database import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# No fallback: a hard-coded key would let anyone forge tokens if the env var is ever missing.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "SECRET_KEY must be set to a random string of at least 32 characters "
        "(generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    )
ALGORITHM = "HS256"
# A working day; there is no refresh flow, so users sign in again after this
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def issue_token(user: User) -> str:
    """The login token for a user, reflecting their state right now.

    tv  - the user's token_version; a later password change/reset makes this token invalid
    mcp - the account must change its password first (lets the frontend route them there)
    """
    return create_access_token(data={
        "sub": user.email,
        "role": user.role,
        "user_id": user.id,
        "site_id": user.site_id,
        "tv": user.token_version or 0,
        "mcp": bool(user.must_change_password),
    })


# While a password change is required, only these are allowed (so the user can actually do it)
ALLOWED_WHEN_PASSWORD_CHANGE_REQUIRED = {"/users/me", "/auth/change-password"}


def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()


def authenticate_user(db: Session, email: str, password: str):
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    return user


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user_by_email(db, email)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )
    # Tokens from before a password change/reset are dead. Tokens issued before this feature
    # existed carry no "tv" and count as version 0, so deploying it does not sign anyone out.
    if payload.get("tv", 0) != (user.token_version or 0):
        raise credentials_exception
    if user.must_change_password and request.url.path not in ALLOWED_WHEN_PASSWORD_CHANGE_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "password_change_required", "message": "You must choose a new password before continuing."},
        )
    return user


def require_role(*roles):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to perform this action"
            )
        return current_user
    return role_checker