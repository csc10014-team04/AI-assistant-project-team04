# owner: Khoi (P1-3 authentication & session management)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import AuthIdentity, AuthProvider, User, UserPreference
from services.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)


class RegisterResponse(BaseModel):
    user_id: int
    username: str
    display_name: str
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    """register a new user with password identity and default preferences"""
    existing_identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == AuthProvider.PASSWORD,
            AuthIdentity.provider_user_id == payload.username,
        )
    )
    if existing_identity is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username is already registered",
        )

    user = User(display_name=payload.display_name)
    db.add(user)
    db.flush()  # obtain auto-generated user.id within current transaction

    identity = AuthIdentity(
        user_id=user.id,
        provider=AuthProvider.PASSWORD,
        provider_user_id=payload.username,
        hashed_password=hash_password(payload.password),
    )
    preference = UserPreference(user_id=user.id)
    db.add_all([identity, preference])
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return RegisterResponse(
        user_id=user.id,
        username=payload.username,
        display_name=user.display_name,
        access_token=token,
        token_type="bearer",
    )


@router.post("/login", response_model=TokenResponse)
def login_user(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """authenticate username and password and issue a bearer jwt"""
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == AuthProvider.PASSWORD,
            AuthIdentity.provider_user_id == payload.username,
        )
    )
    if (
        identity is None
        or identity.hashed_password is None
        or not verify_password(payload.password, identity.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(identity.user_id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=identity.user_id,
    )

