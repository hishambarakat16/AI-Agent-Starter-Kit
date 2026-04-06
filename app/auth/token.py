from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.schemas.auth import TokenData


def _secret_key() -> str:
    key = (os.getenv("JWT_SECRET_KEY") or "").strip()
    if not key:
        raise RuntimeError("JWT_SECRET_KEY is not set")
    return key


def _algorithm() -> str:
    return (os.getenv("JWT_ALGORITHM") or "HS256").strip()


def _expires_minutes() -> int:
    raw = (os.getenv("JWT_EXPIRES_MIN") or "60").strip()
    return int(raw)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=_expires_minutes())
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _secret_key(), algorithm=_algorithm())


def verify_token(token: str, credentials_exception):
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[_algorithm()])
        email: str | None = payload.get("sub")
        if not email:
            raise credentials_exception
        return TokenData(email=email)
    except JWTError:
        raise credentials_exception
