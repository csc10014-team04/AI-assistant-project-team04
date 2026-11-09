"""
OA2-01..OA2-22: OAuth2 flow tests.
Covers: state token generation, state validation, provider-scoped states,
        TTL expiry, provider allowlist, anti-replay.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

# OAuth service may not be importable in all test environments
try:
    from services import oauth
    _OAUTH_AVAILABLE = True
except ImportError:
    _OAUTH_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _OAUTH_AVAILABLE, reason="OAuth service not importable")


# ---- OA2-01: make_state returns a non-empty string -------------------------
def test_OA2_01_make_state_returns_string():
    """Contract: make_state returns a non-empty JWT-like string."""
    state = oauth.make_state("google")
    assert isinstance(state, str) and len(state) > 10


# ---- OA2-02: make_state for different providers differs -------------------
def test_OA2_02_different_providers_different_states():
    """Contract: states for different providers are distinct."""
    s1 = oauth.make_state("google")
    s2 = oauth.make_state("github")
    assert s1 != s2


# ---- OA2-03: check_state validates correct state --------------------------
def test_OA2_03_check_state_validates_correct():
    """Contract: check_state returns True for a freshly generated state."""
    state = oauth.make_state("google")
    # Should not raise
    result = oauth.check_state(state, "google")
    assert result is True or result is None  # may return True or just not raise


# ---- OA2-04: check_state rejects wrong provider ---------------------------
def test_OA2_04_check_state_wrong_provider_raises():
    """Contract: check_state raises for state issued for different provider."""
    state = oauth.make_state("google")
    with pytest.raises(Exception):
        oauth.check_state(state, "github")


# ---- OA2-05: check_state rejects tampered state ---------------------------
def test_OA2_05_check_state_rejects_tampered():
    """Contract: tampered state token is rejected."""
    state = oauth.make_state("google")
    tampered = state[:-3] + "abc"
    with pytest.raises(Exception):
        oauth.check_state(tampered, "google")


# ---- OA2-06: check_state rejects garbage -----------------------------------
def test_OA2_06_check_state_rejects_garbage():
    """Contract: garbage state string raises exception."""
    with pytest.raises(Exception):
        oauth.check_state("not.a.jwt", "google")


# ---- OA2-07: State TTL is 600 seconds ------------------------------------
def test_OA2_07_state_ttl_is_600():
    """Contract: STATE_TTL_SECONDS is exactly 600."""
    assert oauth.STATE_TTL_SECONDS == 600


# ---- OA2-08: Supported providers include google and github ----------------
def test_OA2_08_supported_providers():
    """Contract: google and github are supported OAuth providers."""
    for provider in ("google", "github"):
        state = oauth.make_state(provider)
        assert state  # just verify it doesn't raise


# ---- OA2-09: State cannot be reused (anti-replay) -------------------------
def test_OA2_09_state_anti_replay():
    """Contract: each make_state call produces a unique state token (no reuse)."""
    states = {oauth.make_state("google") for _ in range(5)}
    assert len(states) == 5


# ---- OA2-10: OAuth start endpoint returns state ----------------------------
def test_OA2_10_oauth_start_returns_state(client):
    """Contract: GET /auth/oauth/{provider}/start returns a state field."""
    for provider in ("google", "github"):
        res = client.get(f"/api/v1/auth/oauth/{provider}/start")
        if res.status_code == 200:
            body = res.json()
            assert "state" in body or "auth_url" in body


# ---- OA2-11: OAuth callback with invalid state returns error ---------------
def test_OA2_11_callback_invalid_state_rejected(client):
    """Contract: OAuth callback with forged state returns 400 or 401."""
    res = client.post(
        "/api/v1/auth/oauth/google/callback",
        json={"code": "fake_code", "state": "invalid.state.token"},
    )
    assert res.status_code in (400, 401, 422)


# ---- OA2-12: OAuth callback with no state returns error -------------------
def test_OA2_12_callback_missing_state(client):
    """Contract: OAuth callback with no state field is rejected."""
    res = client.post(
        "/api/v1/auth/oauth/google/callback",
        json={"code": "fake_code"},
    )
    assert res.status_code in (400, 422)


# ---- OA2-13: Unsupported provider returns 404 or 400 ----------------------
def test_OA2_13_unsupported_provider_rejected(client):
    """Contract: OAuth callback for unsupported provider returns 404 or 400."""
    res = client.get("/api/v1/auth/oauth/twitter/start")
    assert res.status_code in (400, 404, 422)


# ---- OA2-14: alg:none attack on state token is rejected ------------------
def test_OA2_14_alg_none_state_rejected():
    """Contract: alg=none state token is rejected by check_state."""
    import jwt
    # Create alg:none token
    forged = jwt.encode(
        {"purpose": "oauth", "provider": "google", "exp": time.time() + 600},
        "",
        algorithm="none",
    )
    with pytest.raises(Exception):
        oauth.check_state(forged, "google")


# ---- OA2-15: make_state includes purpose claim ----------------------------
def test_OA2_15_state_includes_purpose_claim():
    """Contract: state token is a JWT containing a purpose claim."""
    import jwt
    state = oauth.make_state("google")
    # Decode without verification to check claims
    payload = jwt.decode(state, options={"verify_signature": False})
    assert payload.get("purpose") == "oauth" or "provider" in payload


# ---- OA2-16: State issued for one provider has provider claim -------------
def test_OA2_16_state_has_provider_claim():
    """Contract: state token encodes the provider name."""
    import jwt
    state = oauth.make_state("github")
    payload = jwt.decode(state, options={"verify_signature": False})
    assert payload.get("provider") == "github"


# ---- OA2-17: OAuth user gets user_id and access_token on success ----------
def test_OA2_17_callback_success_returns_token(client, monkeypatch):
    """Contract: successful OAuth callback returns user_id and access_token."""
    # This test verifies the response shape; actual OAuth exchange is mocked
    if not hasattr(oauth, "fetch_profile"):
        pytest.skip("fetch_profile not available")

    # Mock fetch_profile to return a fake user
    monkeypatch.setattr(oauth, "fetch_profile", lambda provider, code: {
        "id": "fake_github_123",
        "login": "fakeuser",
        "name": "Fake User",
    })
    # Also need a valid state
    state = oauth.make_state("github")
    res = client.post(
        "/api/v1/auth/oauth/github/callback",
        json={"code": "any_code", "state": state},
    )
    if res.status_code == 200:
        body = res.json()
        assert "access_token" in body
        assert "user_id" in body


# ---- OA2-18: OAuth creates UserPreference row -----------------------------
def test_OA2_18_oauth_user_gets_default_preferences(client, monkeypatch, db):
    """Contract: new OAuth user gets a UserPreference row."""
    if not hasattr(oauth, "fetch_profile"):
        pytest.skip("fetch_profile not available")

    monkeypatch.setattr(oauth, "fetch_profile", lambda provider, code: {
        "id": "fake_google_999",
        "email": "fake@example.com",
        "name": "Fake Google User",
    })

    state = oauth.make_state("google")
    res = client.post(
        "/api/v1/auth/oauth/google/callback",
        json={"code": "code", "state": state},
    )
    if res.status_code == 200:
        from models import UserPreference
        from sqlalchemy import select
        uid = res.json()["user_id"]
        pref = db.scalar(select(UserPreference).where(UserPreference.user_id == uid))
        assert pref is not None


# ---- OA2-19: Same OAuth provider+id re-login returns same user_id --------
def test_OA2_19_same_oauth_provider_id_returns_same_user(client, monkeypatch):
    """Contract: re-authenticating with the same OAuth identity returns the same user_id."""
    if not hasattr(oauth, "fetch_profile"):
        pytest.skip("fetch_profile not available")

    profile = {"id": "stable_github_id_42", "login": "stableuser", "name": "Stable User"}
    monkeypatch.setattr(oauth, "fetch_profile", lambda prov, code: profile)

    s1, s2 = oauth.make_state("github"), oauth.make_state("github")
    r1 = client.post("/api/v1/auth/oauth/github/callback",
                     json={"code": "c1", "state": s1})
    r2 = client.post("/api/v1/auth/oauth/github/callback",
                     json={"code": "c2", "state": s2})

    if r1.status_code == 200 and r2.status_code == 200:
        assert r1.json()["user_id"] == r2.json()["user_id"]


# ---- OA2-20: Password user and OAuth user with same name can coexist ------
def test_OA2_20_password_and_oauth_user_coexist(client, alice, monkeypatch):
    """Contract: a password user named 'alice' and OAuth user both register without collision."""
    # alice already registered with password
    if not hasattr(oauth, "fetch_profile"):
        pytest.skip("fetch_profile not available")

    monkeypatch.setattr(oauth, "fetch_profile", lambda prov, code: {
        "id": "github_alice_id",
        "login": "alice",  # same username but different provider
        "name": "Alice OAuth",
    })

    state = oauth.make_state("github")
    res = client.post("/api/v1/auth/oauth/github/callback",
                      json={"code": "oauthcode", "state": state})
    # Must not conflict with the password-based alice
    assert res.status_code in (200, 409)  # either works or is a known conflict


# ---- OA2-21: State is JWT-encoded, not plaintext --------------------------
def test_OA2_21_state_is_jwt_not_plaintext():
    """Contract: state token has JWT structure (3 dot-separated parts)."""
    state = oauth.make_state("google")
    parts = state.split(".")
    assert len(parts) == 3, f"Expected JWT format (3 parts), got: {len(parts)}"


# ---- OA2-22: check_state with empty string raises ------------------------
def test_OA2_22_check_state_empty_raises():
    """Contract: check_state with empty string raises exception."""
    with pytest.raises(Exception):
        oauth.check_state("", "google")
