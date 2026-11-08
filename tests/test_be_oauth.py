"""OA-01..OA-09: Google / GitHub sign-in (P2-8) with a fake provider (no network)."""
import json

import httpx
import jwt
import pytest
from sqlalchemy import select

from models import AuthIdentity, AuthProvider, User, UserPreference
from routers import oauth
from services.security import JWT_ALGORITHM, JWT_SECRET_KEY, create_access_token

REAL = httpx.Client


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    for p in ("GOOGLE", "GITHUB"):
        monkeypatch.setenv(f"{p}_CLIENT_ID", f"{p.lower()}-id")
        monkeypatch.setenv(f"{p}_CLIENT_SECRET", f"{p.lower()}-secret")


def fake_provider(monkeypatch, profile, token_status=200, access="tok123"):
    """replace the outbound HTTP client with a fake that answers the token and profile calls."""
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith(("token", "access_token")):
            return httpx.Response(token_status, json={"access_token": access} if token_status == 200 else {})
        return httpx.Response(200, json=profile)

    monkeypatch.setattr(oauth.httpx, "Client", lambda **kw: REAL(transport=httpx.MockTransport(handler)))
    return seen


def start(client, provider="google"):
    res = client.get(f"/api/v1/auth/oauth/{provider}/start", params={"redirect_uri": "myapp://cb"})
    assert res.status_code == 200, res.text
    return res.json()


def exchange(client, state, provider="google", code="abc"):
    return client.post(f"/api/v1/auth/oauth/{provider}/exchange", json={"code": code, "redirect_uri": "myapp://cb", "state": state})


def test_OA01_start_returns_consent_url_with_client_id_scope_and_state(client):
    body = start(client, "google")
    assert body["authorize_url"].startswith("https://accounts.google.com/") and "client_id=google-id" in body["authorize_url"]
    assert "scope=openid" in body["authorize_url"] and body["state"] in body["authorize_url"]
    assert start(client, "github")["authorize_url"].startswith("https://github.com/login/oauth/authorize")


def test_OA02_unknown_provider_is_404_and_unconfigured_provider_is_503(client, monkeypatch):
    assert client.get("/api/v1/auth/oauth/facebook/start", params={"redirect_uri": "x"}).status_code == 404
    monkeypatch.delenv("GITHUB_CLIENT_SECRET")
    assert client.get("/api/v1/auth/oauth/github/start", params={"redirect_uri": "x"}).status_code == 503


def test_OA03_first_google_login_creates_user_identity_and_default_preferences(client, db, monkeypatch):
    fake_provider(monkeypatch, {"sub": "g-1001", "name": "Nguyễn An"})
    res = exchange(client, start(client)["state"])
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["is_new_user"] is True and out["display_name"] == "Nguyễn An"
    ident = db.scalar(select(AuthIdentity).where(AuthIdentity.provider == AuthProvider.GOOGLE))
    assert ident.provider_user_id == "g-1001" and ident.hashed_password is None and ident.user_id == out["user_id"]
    assert db.scalar(select(UserPreference).where(UserPreference.user_id == out["user_id"])) is not None


def test_OA04_second_login_reuses_the_account_and_token_works(client, db, monkeypatch):
    fake_provider(monkeypatch, {"sub": "g-1001", "name": "Nguyễn An"})
    first = exchange(client, start(client)["state"]).json()
    second = exchange(client, start(client)["state"]).json()
    assert second["is_new_user"] is False and second["user_id"] == first["user_id"]
    assert len(db.scalars(select(User)).all()) == 1
    me = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {second['access_token']}"})
    assert me.status_code == 200  # the issued token authenticates normally


def test_OA05_github_numeric_id_is_stored_as_text(client, db, monkeypatch):
    fake_provider(monkeypatch, {"id": 4242, "login": "octo", "name": None})
    out = exchange(client, start(client, "github")["state"], "github").json()
    assert out["display_name"] == "octo"  # falls back to the login when no name is public
    assert db.scalar(select(AuthIdentity).where(AuthIdentity.provider == AuthProvider.GITHUB)).provider_user_id == "4242"


def test_OA06_bad_expired_or_wrong_provider_state_is_rejected(client, monkeypatch):
    fake_provider(monkeypatch, {"sub": "x"})
    assert exchange(client, "not-a-jwt").status_code == 400
    expired = jwt.encode({"purpose": "oauth", "provider": "google", "exp": 1}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    assert exchange(client, expired).status_code == 400
    assert exchange(client, start(client, "github")["state"], provider="google").status_code == 400  # github state, google flow


def test_OA07_a_login_token_cannot_be_used_as_oauth_state(client, monkeypatch):
    fake_provider(monkeypatch, {"sub": "x"})
    assert exchange(client, create_access_token(1)).status_code == 400


def test_OA08_provider_errors_become_401_or_502_never_500(client, monkeypatch):
    fake_provider(monkeypatch, {}, token_status=400)
    assert exchange(client, start(client)["state"]).status_code == 502
    fake_provider(monkeypatch, {})  # token ok but no user id in the profile
    assert exchange(client, start(client)["state"]).status_code == 502

    def boom(request):
        raise httpx.ConnectError("provider down")

    monkeypatch.setattr(oauth.httpx, "Client", lambda **kw: REAL(transport=httpx.MockTransport(boom)))
    assert exchange(client, start(client)["state"]).status_code == 502


def test_OA09_secret_is_sent_to_the_provider_only_and_never_returned(client, monkeypatch):
    seen = fake_provider(monkeypatch, {"sub": "g-9", "name": "A"})
    res = exchange(client, start(client)["state"], code="one-time-code")
    token_call = next(r for r in seen if r.url.path.endswith("token"))
    assert b"google-secret" in token_call.content and b"one-time-code" in token_call.content
    assert "google-secret" not in res.text and "tok123" not in res.text
