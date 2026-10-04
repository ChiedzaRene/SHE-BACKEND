"""My account, safety targets and the audit log."""
from datetime import date, timedelta

import pytest

from database import SessionLocal
from models.app_setting import AppSetting
from models.audit_log import AuditLog
from models.user import User
from routers import auth as auth_router
from services.auth_services import create_access_token, hash_password, verify_password

OLD, NEW = "old-password-1", "brand-new-pass-2"


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    auth_router.limiter.reset()  # change-password is limited to 5/min per IP
    yield


@pytest.fixture(scope="module")
def own_account(client):
    """A user these tests may freely change (other tests must keep their own passwords)."""
    db = SessionLocal()
    db.add(User(id=90, email="me90@x.com", password=hash_password(OLD), role="she_team", full_name="Before"))
    db.commit()
    db.close()
    # A dict so tests can swap in the fresh token a password change returns
    yield {"Authorization": "Bearer " + create_access_token({"sub": "me90@x.com"})}
    db = SessionLocal()
    db.query(User).filter(User.id == 90).delete()
    db.query(AppSetting).delete()  # leave defaults for the other test files
    db.commit()
    db.close()


def stored_password_ok(candidate):
    db = SessionLocal()
    try:
        return verify_password(candidate, db.query(User).filter(User.id == 90).one().password)
    finally:
        db.close()


# ─── My account ─────────────────────────────────────────────────────────────

def test_change_password_requires_login(client):
    r = client.post("/auth/change-password", json={"current_password": OLD, "new_password": NEW})
    assert r.status_code == 401


def test_change_password_rules(client, own_account):
    post = lambda body: client.post("/auth/change-password", json=body, headers=own_account)
    wrong = post({"current_password": "nope", "new_password": NEW})
    assert wrong.status_code == 400 and "incorrect" in wrong.json()["detail"]   # 400, never 401 (401 logs the user out)
    assert post({"current_password": OLD, "new_password": "short"}).status_code == 422
    assert post({"current_password": OLD, "new_password": OLD}).status_code == 400
    assert stored_password_ok(OLD)  # nothing above changed it


def test_change_password_success_and_audit(client, own_account):
    old_headers = dict(own_account)
    r = client.post("/auth/change-password", json={"current_password": OLD, "new_password": NEW}, headers=own_account)
    assert r.status_code == 200
    # Changing the password signs out older sessions; the reply carries a fresh token for this one
    assert client.get("/users/me", headers=old_headers).status_code == 401
    own_account["Authorization"] = "Bearer " + r.json()["access_token"]
    assert client.get("/users/me", headers=own_account).status_code == 200
    assert stored_password_ok(NEW) and not stored_password_ok(OLD)
    db = SessionLocal()
    entry = db.query(AuditLog).filter(AuditLog.action == "CHANGE_PASSWORD", AuditLog.user_email == "me90@x.com").first()
    db.close()
    assert entry is not None and NEW not in (entry.details or "")   # the password itself is never logged


def test_change_password_is_rate_limited(client, own_account):
    codes = [client.post("/auth/change-password", json={"current_password": "x", "new_password": NEW},
                         headers=own_account).status_code for _ in range(7)]
    assert codes[:5] == [400] * 5 and codes[5] == 429


def test_update_own_name(client, own_account):
    r = client.patch("/users/me", json={"full_name": "  <b>Tendai</b> Moyo "}, headers=own_account)
    assert r.status_code == 200 and r.json()["full_name"] == "Tendai Moyo"          # tags stripped, trimmed
    assert client.patch("/users/me", json={"full_name": ""}, headers=own_account).status_code == 422
    # role and email cannot be changed this way
    r = client.patch("/users/me", json={"full_name": "Same", "role": "super_admin", "email": "x@x.com"},
                     headers=own_account)
    assert r.status_code == 200 and r.json()["role"] == "she_team" and r.json()["email"] == "me90@x.com"


# ─── Safety targets ─────────────────────────────────────────────────────────

def test_targets_defaults_visible_to_everyone(client, auth):
    for who in ("mgr", "she", "admin"):
        r = client.get("/settings/safety-targets", headers=auth[who])
        assert r.status_code == 200
        assert (r.json()["trir_limit"], r.json()["ltifr_limit"], r.json()["rate_basis_hours"]) == (1.5, 0.5, 200000)
    assert client.get("/settings/safety-targets").status_code == 401


def test_only_admins_can_change_targets(client, auth):
    body = {"trir_limit": 2.0, "ltifr_limit": 1.0}
    assert client.put("/settings/safety-targets", json=body).status_code == 401
    assert client.put("/settings/safety-targets", json=body, headers=auth["mgr"]).status_code == 403
    assert client.put("/settings/safety-targets", json=body, headers=auth["she"]).status_code == 403


def test_target_validation(client, auth):
    put = lambda b: client.put("/settings/safety-targets", json=b, headers=auth["admin"]).status_code
    assert put({"trir_limit": 0, "ltifr_limit": 1}) == 422
    assert put({"trir_limit": -1, "ltifr_limit": 1}) == 422
    assert put({"trir_limit": 1, "ltifr_limit": 1000}) == 422
    assert put({"trir_limit": "abc", "ltifr_limit": 1}) == 422
    assert put({"trir_limit": 1}) == 422


def test_changing_targets_changes_report_status_and_is_logged(client, auth):
    def board():
        doc = client.get("/reports/leaderboard?period=ytd", headers=auth["she"]).json()
        return doc, {r[1]: r for r in doc["tables"][0]["rows"]}

    # Make sure at least one site has an hours-based rate so it can be flagged
    from datetime import datetime
    from models.incident import Incident
    from models.site import Site
    from models.site_hours import SiteHours
    db = SessionLocal()
    db.add(Site(id=95, name="Targets Site", address="t"))
    db.flush()
    db.add(SiteHours(site_id=95, period=date.today().replace(day=1), hours_worked=100000, entered_by=1))
    db.add(Incident(site_id=95, user_id=1, type="injury", description="targets test", severity="low",
                    lost_time_days=0, occurred_at=datetime.now()))
    db.commit()
    db.close()
    try:
        doc, rows = board()
        assert rows["Targets Site"][5] == "2.00" and rows["Targets Site"][9] == "Action required"  # 2.00 > default 1.5
        assert "TRIR 1.5" in doc["notes"][0]

        r = client.put("/settings/safety-targets", json={"trir_limit": 3.0, "ltifr_limit": 0.5}, headers=auth["admin"])
        assert r.status_code == 200 and r.json()["trir_limit"] == 3.0
        assert client.get("/settings/safety-targets", headers=auth["mgr"]).json()["trir_limit"] == 3.0

        doc, rows = board()
        assert rows["Targets Site"][9] == "Within limits"                      # the new limit is used by reports
        assert "TRIR 3" in doc["notes"][0]

        db = SessionLocal()
        entry = db.query(AuditLog).filter(AuditLog.action == "UPDATE_SETTINGS").order_by(AuditLog.id.desc()).first()
        db.close()
        assert "TRIR limit 1.5 -> 3" in entry.details
    finally:
        db = SessionLocal()
        from models.incident import Incident as I
        from models.site_hours import SiteHours as H
        db.query(I).filter(I.site_id == 95).delete()
        db.query(H).filter(H.site_id == 95).delete()
        db.query(Site).filter(Site.id == 95).delete()
        db.query(AppSetting).delete()
        db.commit()
        db.close()


# ─── Audit log ──────────────────────────────────────────────────────────────

def test_audit_log_is_super_admin_only(client, auth):
    for who in ("admin", "she", "mgr"):
        assert client.get("/audit-logs/", headers=auth[who]).status_code == 403
        assert client.get("/audit-logs/facets", headers=auth[who]).status_code == 403
    assert client.get("/audit-logs/").status_code == 401
    assert client.get("/audit-logs/", headers=auth["super"]).status_code == 200


def test_audit_log_filters_paging_and_facets(client, auth):
    sup = auth["super"]
    total = int(client.get("/audit-logs/?limit=1", headers=sup).headers["x-total-count"])
    assert total >= 3
    page = client.get("/audit-logs/?limit=2&offset=1", headers=sup)
    assert len(page.json()) == 2 and page.headers["x-total-count"] == str(total)
    ids = [e["id"] for e in client.get("/audit-logs/?limit=500", headers=sup).json()]
    assert ids == sorted(ids, reverse=True)                                       # newest first

    by_action = client.get("/audit-logs/?action=CHANGE_PASSWORD", headers=sup).json()
    assert by_action and all(e["action"] == "CHANGE_PASSWORD" for e in by_action)
    by_user = client.get("/audit-logs/?user=ME90", headers=sup).json()            # case-insensitive substring
    assert by_user and all("me90" in e["user_email"] for e in by_user)
    assert client.get("/audit-logs/?user=%25", headers=sup).json() == []         # "%" is literal, not a wildcard

    today = date.today().isoformat()
    assert client.get(f"/audit-logs/?start={today}&end={today}", headers=sup).json()
    old = (date.today() - timedelta(days=30)).isoformat()
    assert client.get(f"/audit-logs/?end={old}", headers=sup).json() == []
    assert client.get("/audit-logs/?limit=0", headers=sup).status_code == 422
    assert client.get("/audit-logs/?limit=501", headers=sup).status_code == 422

    facets = client.get("/audit-logs/facets", headers=sup).json()
    assert "CHANGE_PASSWORD" in facets["actions"] and "users" in facets["resources"]
    assert "me90@x.com" in facets["users"] and facets["users"] == sorted(set(facets["users"]))  # each email once, A-Z
    assert facets["action_labels"]["RESET_PASSWORD"] == "Password reset by an admin"
    assert facets["resource_labels"]["site_hours"] == "Hours worked"
    labels = [facets["action_labels"][a] for a in facets["actions"]]
    assert labels == sorted(labels, key=str.lower)                      # dropdown is A-Z by the name people read
