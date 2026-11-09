# [pic: khoi] p1-3 password hashing, jwt & current user guard (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import os
from datetime import datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import UTC_TZ, get_db
from models import User

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production-32b")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(plain_password: str) -> str:
    """
    input: plain_password (str) submitted during account registration.
    core logic: generate a random per-password salt and compute bcrypt digest.
    output: str containing utf-8 bcrypt hash string safe for mysql storage.
    typical flow: plain str -> encode utf-8 -> bcrypt.hashpw with salt -> decode utf-8.
    """
    salt = bcrypt.gensalt()  # random 16-byte salt prevents rainbow-table attacks
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    input: plain_password (str) from login attempt and hashed_password (str) from db.
    core logic: run constant-time bcrypt comparison while catching malformed hash formats.
    output: bool (True when password matches digest, False on mismatch or corrupted hash).
    typical flow: valid password -> True; wrong password -> False; invalid salt string -> False.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False  # avoid 500 crash if stored hash format is corrupted


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    """
    input: user_id (int) and optional custom lifetime expires_delta (timedelta | None).
    core logic: build jwt claims (sub, iat, exp) in utc and sign with HS256 secret key.
    output: str containing compact signed jwt bearer token.
    typical flow: compute utc now & exp -> pack sub=str(user_id) -> jwt.encode -> token str.
    """
    now = datetime.now(UTC_TZ)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),  # rfc 7519 requires subject claim as string
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """
    input: token (str) extracted from HTTP Authorization Bearer header.
    core logic: verify HS256 signature and expiration timestamp, then parse integer user_id.
    output: int representing authenticated user_id (or raises HTTP 401 on any token flaw).
    typical flow: valid token -> int(sub); expired/tampered/missing sub -> raise 401.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise credentials_error  # reject token missing subject claim
        return int(sub)
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise credentials_error from exc


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    """
    input: db (Session) and bearer token (str) injected by fastapi dependencies.
    core logic: decode token to user_id and fetch corresponding User row from mysql.
    output: User orm instance for the caller (or raises HTTP 401 if token/account invalid).
    typical flow: request with Bearer token -> decode user_id -> query users table -> return User.
    """
    user_id = decode_access_token(token)
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user account not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
