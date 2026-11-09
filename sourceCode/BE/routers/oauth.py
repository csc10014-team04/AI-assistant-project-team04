# owner: Backend (P2-8 Google / GitHub OAuth2 sign-in via the authorization-code flow)
import os
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import AuthIdentity, AuthProvider, User, UserPreference
from services.security import JWT_ALGORITHM as ALGORITHM, JWT_SECRET_KEY, create_access_token

router = APIRouter(prefix="/api/v1/auth/oauth", tags=["auth"])

STATE_TTL_SECONDS = 600  # the user has 10 minutes to finish the provider's consent screen

PROVIDERS: dict[str, dict[str, str]] = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "profile": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "id_field": "sub",
        "name_field": "name",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "profile": "https://api.github.com/user",
        "scope": "read:user",
        "id_field": "id",
        "name_field": "name",
    },
}


class StartResponse(BaseModel):
    authorize_url: str
    state: str


class ExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    redirect_uri: str = Field(min_length=1, max_length=512)
    state: str = Field(min_length=1, max_length=2048)


class OAuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    display_name: str
    is_new_user: bool


def _provider(name: str) -> dict[str, str]:
    cfg = PROVIDERS.get(name)
    if cfg is None:
        raise HTTPException(404, "unknown oauth provider")
    return cfg


def _credentials(name: str) -> tuple[str, str]:
    client_id = os.getenv(f"{name.upper()}_CLIENT_ID", "").strip()
    secret = os.getenv(f"{name.upper()}_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        raise HTTPException(503, f"{name} sign-in is not configured on this server")
    return client_id, secret


def make_state(provider: str) -> str:
    """signed, short-lived anti-CSRF token binding the flow to one provider."""
    return jwt.encode({"purpose": "oauth", "provider": provider, "exp": int(time.time()) + STATE_TTL_SECONDS},
                      JWT_SECRET_KEY, algorithm=ALGORITHM)


def check_state(state: str, provider: str) -> None:
    try:
        claims = jwt.decode(state, JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(400, "invalid or expired oauth state") from exc
    if claims.get("purpose") != "oauth" or claims.get("provider") != provider:
        raise HTTPException(400, "oauth state does not match this provider")


@router.get("/{provider}/start", response_model=StartResponse)
def start(provider: str, redirect_uri: str = Query(min_length=1, max_length=512)):
    """step 1: give the app the provider's consent-screen URL (and a signed `state` to send back)."""
    cfg = _provider(provider)
    client_id, _ = _credentials(provider)
    state = make_state(provider)
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                       "scope": cfg["scope"], "state": state})
    return StartResponse(authorize_url=f"{cfg['authorize']}?{query}", state=state)


def fetch_profile(provider: str, code: str, redirect_uri: str) -> tuple[str, str]:
    """swap the one-time code for an access token, then read the user's stable id and display name."""
    cfg = _provider(provider)
    client_id, secret = _credentials(provider)
    try:
        with httpx.Client(timeout=10.0) as http:
            tok = http.post(cfg["token"], headers={"Accept": "application/json"}, data={
                "client_id": client_id, "client_secret": secret, "code": code,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
            tok.raise_for_status()
            access = tok.json().get("access_token")
            if not access:
                raise HTTPException(401, "provider refused the authorization code")
            prof = http.get(cfg["profile"], headers={"Authorization": f"Bearer {access}", "Accept": "application/json"})
            prof.raise_for_status()
            data = prof.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "could not reach the sign-in provider") from exc
    subject = data.get(cfg["id_field"])
    if subject in (None, ""):
        raise HTTPException(502, "provider returned no user id")
    name = data.get(cfg["name_field"]) or data.get("login") or data.get("email") or f"{provider}-user"
    return str(subject), str(name)[:100]


@router.post("/{provider}/exchange", response_model=OAuthTokenResponse)
def exchange(provider: str, body: ExchangeRequest, db: Session = Depends(get_db)):
    """
    step 2: the app returns the `code` the provider gave it. We verify `state`, ask the provider who the user
    is, then log in the matching account or create one (User + AuthIdentity without a password + default
    UserPreference, exactly like registration). The provider's own access token is never stored or returned.
    """
    _provider(provider)
    check_state(body.state, provider)
    subject, name = fetch_profile(provider, body.code, body.redirect_uri)
    kind = AuthProvider(provider)
    identity = db.scalar(select(AuthIdentity).where(AuthIdentity.provider == kind, AuthIdentity.provider_user_id == subject))
    is_new = identity is None
    if identity is None:
        user = User(display_name=name)
        db.add(user)
        db.flush()
        identity = AuthIdentity(user_id=user.id, provider=kind, provider_user_id=subject, hashed_password=None)
        db.add_all([identity, UserPreference(user_id=user.id)])
        db.commit()
    user = db.get(User, identity.user_id)
    return OAuthTokenResponse(access_token=create_access_token(user.id), user_id=user.id,
                              display_name=user.display_name, is_new_user=is_new)
