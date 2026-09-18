"""Shared authentication dependencies. Production and local access both fail closed."""
import os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from belzakupki_db.models import User, Tenant
from belzakupki_db.session import get_session

def signing_secret() -> str:
    secret = os.getenv("API_SECRET_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("API_SECRET_KEY must contain at least 32 characters")
    return secret


def validate_security_config() -> None:
    signing_secret()

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 часа

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, signing_secret(), algorithm=JWT_ALGORITHM)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: Session = Depends(get_session)
) -> User:
    """Authenticate explicitly; missing credentials never create or select a user."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    try:
        payload = jwt.decode(token, signing_secret(), algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
        
    user = session.query(User).filter(User.email == email).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active or not user.tenant.is_active:
        raise HTTPException(status_code=401, detail="User is inactive")
    return user


def get_current_tenant(
    current_user: User = Depends(get_current_user)
) -> Tenant:
    """Извлекает организацию (tenant) текущего пользователя."""
    return current_user.tenant


def get_optional_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: Session = Depends(get_session)
) -> User | None:
    """Опционально извлекает пользователя. Возвращает None, если авторизация отсутствует."""
    if not token:
        return None
    try:
        return get_current_user(token, session)
    except HTTPException:
        return None


def get_optional_current_tenant(
    current_user: User | None = Depends(get_optional_current_user)
) -> Tenant | None:
    """Опционально возвращает организацию (tenant) пользователя."""
    return current_user.tenant if current_user else None


def get_current_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """Гарантирует, что текущий пользователь является администратором."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Доступ запрещен. Требуются права администратора."
        )
    return current_user



