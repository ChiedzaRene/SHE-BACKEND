"""Sign out everywhere, forced password change after an admin reset, and the audit trail."""
import pytest
from jose import jwt
from sqlalchemy import create_engine, inspect, text

from database import SessionLocal
from models.audit_log import AuditLog
from models.user import User
from routers import auth as auth_router
from services.auth_services import ALGORITHM, SECRET_KEY, create_access_token, hash_password, issue_token
from services.migrations import ensure_new_columns

TEMP, CHOSEN = "temporary-pass-1", "my-own-pass-22"


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    auth_router.limiter.reset()
    yield


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    db = SessionLocal()
    db.query(User).filter(User.email.like("pwsec-%")).delete(synchronize_session=False)
    db.commit()
    db.close()


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def token_for(email):
    db = SessionLocal()
    try:
        return issue_token(db.query(User).filter(User.email == email).one())
    finally:
        db.close()


def make_user(email, role="she_team", password=TEMP, forced=False):
    db = SessionLocal()
    db.add(User(email=email, password=hash_password(password), role=role, must_change_password=forced))
    db.commit()
    uid = db.query(User).filter(User.email == email).one().id
    db.close()
    return uid


def user_id(email):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).one().id
    finally:
        db.close()


def row(email):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).one()
        return u.must_change_password, u.token_version
    finally:
        db.close()


def audit(action, text_in=None):
    db = SessionLocal()
    try:
        q = db.query(AuditLog).filter(AuditLog.action == action)
        return [e for e in q.all() if text_in is None or text_in in (e.details or "")]
    finally:
        db.close()


# ─── Migration ──────────────────────────────────────────────────────────────

def test_migration_adds_columns_to_an_old_users_table_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as c:   # the users table as it was before this feature
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password TEXT, role TEXT)"))
        c.execute(text("INSERT INTO users (email, password, role) VALUES ('old@x.com', 'h', 'admin')"))
    assert ensure_new_columns(engine) == ["users.must_change_password", "users.token_version"]
    assert ensure_new_columns(engine) == []                       # second run changes nothing
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert {"must_change_password", "token_version"} <= cols
    with engine.connect() as c:                                    # existing users get safe defaults
        assert tuple(c.execute(text("SELECT must_change_password, token_version FROM users")).one()) == (0, 0)


def test_tokens_issued_before_this_feature_still_work(client):
    make_user("pwsec-legacy@x.com")
    legacy = create_access_token({"sub": "pwsec-legacy@x.com"})    # no "tv" claim, like tokens already in browsers
    assert client.get("/users/me", headers=hdr(legacy)).status_code == 200


# ─── Sign out everywhere ────────────────────────────────────────────────────

def test_changing_your_password_signs_out_other_sessions(client):
    make_user("pwsec-self@x.com")
    laptop, phone = token_for("pwsec-self@x.com"), token_for("pwsec-self@x.com")
    r = client.post("/auth/change-password", json={"current_password": TEMP, "new_password": CHOSEN}, headers=hdr(laptop))
    assert r.status_code == 200
    assert client.get("/users/me", headers=hdr(phone)).status_code == 401      # other device: signed out
    assert client.get("/users/me", headers=hdr(laptop)).status_code == 401     # the old token too...
    assert client.get("/users/me", headers=hdr(r.json()["access_token"])).status_code == 200  # ...but this session goes on
    assert row("pwsec-self@x.com") == (False, 1)


# ─── Admin reset ────────────────────────────────────────────────────────────

def test_admin_reset_forces_a_change_and_signs_the_user_out(client, auth):
    make_user("pwsec-victim@x.com")
    uid = user_id("pwsec-victim@x.com")
    old = token_for("pwsec-victim@x.com")
    r = client.put(f"/users/{uid}", json={"password": "Reset-by-admin-9"}, headers=auth["admin"])
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert client.get("/users/me", headers=hdr(old)).status_code == 401        # signed out everywhere
    assert row("pwsec-victim@x.com") == (True, 1)

    # They can sign in with the temporary password, and the token tells the frontend what to do
    login = client.post("/auth/login", data={"username": "pwsec-victim@x.com", "password": "Reset-by-admin-9"})
    assert login.status_code == 200
    claims = jwt.get_unverified_claims(login.json()["access_token"])
    assert claims["mcp"] is True and claims["tv"] == 1


def test_admin_reset_is_audited_and_never_logs_the_password(client, auth):
    make_user("pwsec-audited@x.com")
    uid = user_id("pwsec-audited@x.com")
    client.put(f"/users/{uid}", json={"password": "Secret-reset-77"}, headers=auth["admin"])
    entries = audit("RESET_PASSWORD", "pwsec-audited@x.com")
    assert len(entries) == 1
    assert entries[0].user_email == "admin@x.com" and "Secret-reset-77" not in entries[0].details
    assert "signed out everywhere" in entries[0].details
    # editing a user WITHOUT a password is not a reset
    before = len(audit("RESET_PASSWORD"))
    client.put(f"/users/{uid}", json={"full_name": "Renamed"}, headers=auth["admin"])
    assert len(audit("RESET_PASSWORD")) == before and row("pwsec-audited@x.com") == (True, 1)


def test_super_admin_route_resets_the_same_way(client, auth):
    make_user("pwsec-super@x.com")
    uid = user_id("pwsec-super@x.com")
    old = token_for("pwsec-super@x.com")
    assert client.patch(f"/admin/users/{uid}", json={"password": "Another-temp-55"}, headers=auth["super"]).status_code == 200
    assert client.get("/users/me", headers=hdr(old)).status_code == 401
    assert row("pwsec-super@x.com") == (True, 1)
    assert audit("RESET_PASSWORD", "pwsec-super@x.com")


def test_admin_setting_their_own_password_is_a_normal_change(client, auth):
    admin_id = user_id("admin@x.com")
    before = row("admin@x.com")
    n = len(audit("RESET_PASSWORD"))
    r = client.put(f"/users/{admin_id}", json={"password": "newpassword123"}, headers=auth["admin"])
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert client.get("/users/me", headers=auth["admin"]).status_code == 200   # still signed in
    assert row("admin@x.com") == before and len(audit("RESET_PASSWORD")) == n


# ─── Forced change ──────────────────────────────────────────────────────────

def test_new_accounts_made_by_an_admin_must_change_their_password(client, auth):
    r = client.post("/users/", json={"email": "pwsec-new@x.com", "password": TEMP, "role": "site_manager"},
                    headers=auth["admin"])
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    r = client.post("/auth/register", json={"email": "pwsec-new2@x.com", "password": TEMP, "role": "she_team"},
                    headers=auth["admin"])
    assert r.status_code == 200 and row("pwsec-new2@x.com")[0] is True


def test_forced_user_is_blocked_everywhere_except_changing_the_password(client):
    make_user("pwsec-forced@x.com", forced=True)
    t = token_for("pwsec-forced@x.com")
    blocked = client.get("/sites/", headers=hdr(t))
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "password_change_required"
    assert client.get("/incidents/", headers=hdr(t)).status_code == 403
    assert client.get("/reports/leaderboard", headers=hdr(t)).status_code == 403
    me = client.get("/users/me", headers=hdr(t))
    assert me.status_code == 200 and me.json()["must_change_password"] is True
    # the temporary password cannot be "changed" to itself
    same = client.post("/auth/change-password", json={"current_password": TEMP, "new_password": TEMP}, headers=hdr(t))
    assert same.status_code == 400

    done = client.post("/auth/change-password", json={"current_password": TEMP, "new_password": CHOSEN}, headers=hdr(t))
    assert done.status_code == 200
    fresh = done.json()["access_token"]
    assert jwt.get_unverified_claims(fresh)["mcp"] is False
    assert client.get("/sites/", headers=hdr(fresh)).status_code == 200       # unblocked
    assert client.get("/sites/", headers=hdr(t)).status_code == 401           # the temporary session is gone
    assert row("pwsec-forced@x.com") == (False, 1)


def test_users_without_the_flag_are_unaffected(client, auth):
    for who in ("admin", "she", "mgr", "super"):
        assert client.get("/users/me", headers=auth[who]).json()["must_change_password"] is False
    assert client.get("/sites/", headers=auth["she"]).status_code == 200


def test_secret_key_signed_claims_are_checked(client):
    make_user("pwsec-forge@x.com")
    forged = jwt.encode({"sub": "pwsec-forge@x.com", "tv": 5}, SECRET_KEY, algorithm=ALGORITHM)
    assert client.get("/users/me", headers=hdr(forged)).status_code == 401    # right signature, wrong version
