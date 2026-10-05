from datetime import datetime, timedelta, timezone

from database import Base, SessionLocal
from models.audit_log import AuditLog
from models.incident import Incident
from routers import auth as auth_router
from services import login_throttle
from services.retention import purge_old_audit_logs
from services.text_cleanup import fix_escaped_text
from tests.conftest import PASSWORD


def _login(client, email, password):
    return client.post("/auth/login", data={"username": email, "password": password})


def test_wrong_passwords_lock_only_that_account(client):
    auth_router.limiter.reset()
    login_throttle.reset()
    for _ in range(login_throttle.MAX_FAILURES):
        assert _login(client, "super@x.com", "wrong-pass-1").status_code == 401
    blocked = _login(client, "super@x.com", PASSWORD)
    assert blocked.status_code == 429
    assert "wait" in blocked.json()["detail"].lower()
    assert "Retry-After" in blocked.headers
    # A colleague on the same network is not affected
    assert _login(client, "admin@x.com", PASSWORD).status_code == 200
    login_throttle.reset()
    assert _login(client, "super@x.com", PASSWORD).status_code == 200


def test_successful_login_clears_the_count(client):
    login_throttle.reset()
    for _ in range(login_throttle.MAX_FAILURES - 1):
        _login(client, "admin@x.com", "wrong-pass-1")
    assert _login(client, "admin@x.com", PASSWORD).status_code == 200
    for _ in range(login_throttle.MAX_FAILURES - 1):
        assert _login(client, "admin@x.com", "wrong-pass-1").status_code == 401
    login_throttle.reset()


def test_many_people_can_sign_in_from_one_address(client):
    auth_router.limiter.reset()
    login_throttle.reset()
    for _ in range(12):  # the old limit was 5 per minute for the whole office
        assert _login(client, "admin@x.com", PASSWORD).status_code == 200


def test_audit_retention_removes_only_old_entries():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    old = AuditLog(user_email="old@x.com", user_role="admin", action="LOGIN", resource="auth",
                   timestamp=now - timedelta(days=800))
    recent = AuditLog(user_email="recent@x.com", user_role="admin", action="LOGIN", resource="auth",
                      timestamp=now - timedelta(days=10))
    db.add_all([old, recent])
    db.commit()
    try:
        assert purge_old_audit_logs(db, days=730) >= 1
        emails = {e for (e,) in db.query(AuditLog.user_email).all()}
        assert "old@x.com" not in emails and "recent@x.com" in emails
    finally:
        db.query(AuditLog).filter(AuditLog.user_email == "recent@x.com").delete()
        db.commit()
        db.close()


def test_new_text_is_saved_without_html_codes(client, auth):
    r = client.post("/incidents/", json={
        "type": "near_miss", "description": "Fuel & Lubricants <b>spill</b> a > b", "severity": "low",
        "site_id": 1,
    }, headers=auth["admin"])
    assert r.status_code in (200, 201), r.text
    text = r.json()["description"]
    assert "&amp;" not in text and "&gt;" not in text
    assert "Fuel & Lubricants" in text and "<b>" not in text
    db = SessionLocal()
    db.query(Incident).filter(Incident.id == r.json()["id"]).delete()
    db.commit()
    db.close()


def test_cleanup_repairs_old_garbled_text_and_is_dry_by_default():
    db = SessionLocal()
    row = AuditLog(user_email="fix@x.com", user_role="admin", action="LOGIN", resource="auth",
                   details="Fuel &amp; Lubricants -&gt; ok")
    db.add(row)
    db.commit()
    try:
        assert fix_escaped_text(db, Base.metadata)["audit_logs.details"] >= 1
        db.refresh(row)
        assert "&amp;" in row.details  # dry run wrote nothing
        fix_escaped_text(db, Base.metadata, apply=True)
        db.refresh(row)
        assert row.details == "Fuel & Lubricants -> ok"
    finally:
        db.delete(row)
        db.commit()
        db.close()


def test_incident_summary_counts_and_site_scope(client, auth):
    admin = client.get("/incidents/summary", headers=auth["admin"])
    assert admin.status_code == 200
    body = admin.json()
    assert body["total"] == sum(t["value"] for t in body["by_type"])
    assert 0 <= body["open"] <= body["total"]
    assert body["total"] == sum(s["value"] for s in body["by_site"])
    everything = len(client.get("/incidents/", headers=auth["admin"]).json())
    assert body["total"] == everything
    mine = client.get("/incidents/summary", headers=auth["mgr"]).json()
    assert mine["total"] == len(client.get("/incidents/", headers=auth["mgr"]).json())
    assert {s["site_id"] for s in mine["by_site"]} <= {1}
    assert client.get("/incidents/summary").status_code == 401


def test_site_without_a_phone_number_can_be_saved(client, auth):
    body = {"name": "No Phone Depot", "address": "1 Test Road", "latitude": -17.8, "longitude": 31.0, "contact_number": ""}
    r = client.post("/sites/", json=body, headers=auth["admin"])
    assert r.status_code in (200, 201), r.text
    assert r.json()["contact_number"] is None
    site_id = r.json()["id"]
    edited = client.put(f"/sites/{site_id}", json={**body, "contact_number": "  "}, headers=auth["admin"])
    assert edited.status_code == 200 and edited.json()["contact_number"] is None
    bad = client.post("/sites/", json={**body, "name": "Bad Phone", "contact_number": "call me"}, headers=auth["admin"])
    assert bad.status_code == 422
    client.delete(f"/sites/{site_id}", headers=auth["admin"])
