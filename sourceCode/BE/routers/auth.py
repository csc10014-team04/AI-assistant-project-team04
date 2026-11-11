# owner: Khoi (P1-3 authentication & session management)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import AuthIdentity, AuthProvider, User, UserPreference
from services.security import create_access_token, get_current_user, hash_password, verify_password

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
    display_name: str


class UpdateUsernameRequest(BaseModel):
    new_username: str = Field(..., min_length=3, max_length=255)


class UpdateUsernameResponse(BaseModel):
    user_id: int
    username: str
    message: str = "username updated successfully"


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    """
    input: payload (RegisterRequest: username, password, display_name) and db (Session).
    core logic: check duplicate username, atomically insert User + AuthIdentity + UserPreference, sign jwt.
    output: RegisterResponse (HTTP 201) with user_id and bearer token, or HTTP 409 if username exists.
    typical flow: new username -> insert 3 linked rows -> commit -> issue jwt; duplicate -> raise 409.
    """
    existing_identity = db.scalar(
        select(AuthIdentity).where(
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
    db.flush()  # obtain auto-generated user.id before committing transaction

    identity = AuthIdentity(
        user_id=user.id,
        provider=AuthProvider.PASSWORD,
        provider_user_id=payload.username,
        hashed_password=hash_password(payload.password),  # store bcrypt hash only
    )
    preference = UserPreference(user_id=user.id)  # initialize 23:30-06:30 sleep & 15m grid defaults
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
    """
    input: payload (LoginRequest: username, password) and db (Session).
    core logic: look up password identity by username and verify plaintext password against bcrypt hash.
    output: TokenResponse (HTTP 200) containing signed jwt token and user_id, or HTTP 401 on failure.
    typical flow: valid credentials -> issue jwt (200); unknown user or wrong password -> raise 401.
    """
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

    token = create_access_token(identity.user_id)  # sign fresh session token for user
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=identity.user_id,
        display_name=identity.user.display_name,
    )


@router.patch("/username", response_model=UpdateUsernameResponse)
def update_username(
    payload: UpdateUsernameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UpdateUsernameResponse:
    """
    input: payload (UpdateUsernameRequest: new_username), db (Session), current_user (User).
    core logic: verify new_username is not taken by another user, then update auth_identity.
    output: UpdateUsernameResponse on success, or HTTP 409 Conflict if new_username is taken.
    typical flow: check duplicate across all users -> update provider_user_id -> commit -> return.
    """
    existing_identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider_user_id == payload.new_username,
            AuthIdentity.user_id != current_user.id,
        )
    )
    if existing_identity is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username is already taken by another account",
        )

    user_identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == current_user.id,
            AuthIdentity.provider == AuthProvider.PASSWORD,
        )
    )
    if user_identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="password identity not found for current user",
        )

    user_identity.provider_user_id = payload.new_username
    db.commit()
    db.refresh(user_identity)

    return UpdateUsernameResponse(
        user_id=current_user.id,
        username=user_identity.provider_user_id,
        message="username updated successfully",
    )
