"""Filtering the audit log by person: exact matching, the people list, the summary, and what gets recorded."""
from datetime import date

import pytest

from database import SessionLocal
from models.audit_log import AuditLog
from models.user import User
from routers import auth as auth_router
from services.audit_service import log_action
from services.auth_services import hash_password

PW = "password123"


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    auth_router.limiter.reset()
    yield


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    db = SessionLocal()
    db.query(AuditLog).filter(AuditLog.user_email.like("%@trail.com")).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.user_email.like("ghost%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like("%@trail.com")).delete(synchronize_session=False)
    db.commit()
    db.close()


def make_user(email, role="she_team", name=None, active=True):
    db = SessionLocal()
    db.add(User(email=email, password=hash_password(PW), role=role, full_name=name, is_active=active))
    db.commit()
    db.close()


def logs(**filters):
    db = SessionLocal()
    try:
        return db.query(AuditLog).filter_by(**filters).order_by(AuditLog.id).all()
    finally:
        db.close()


def write(email, action, role="she_team", n=1):
    db = SessionLocal()
    user = User(email=email, role=role)
    for i in range(n):
        log_action(db=db, user=user, action=action, resource="incidents", resource_id=i + 1, details=f"{action} {i}")
    db.close()


# ─── exact vs. partial matching ─────────────────────────────────────────────

def test_picking_a_person_shows_exactly_that_person(client, auth):
    write("pa@trail.com", "CREATE_INCIDENT")
    write("spa@trail.com", "CREATE_INCIDENT")             # contains "pa@trail.com" inside it
    exact = client.get("/audit-logs/?email=pa@trail.com", headers=auth["super"]).json()
    assert exact and {e["user_email"] for e in exact} == {"pa@trail.com"}
    assert client.get("/audit-logs/?email=PA@TRAIL.COM", headers=auth["super"]).json() == exact   # case does not matter
    loose = client.get("/audit-logs/?user=pa@trail.com&limit=500", headers=auth["super"]).json()
    assert {e["user_email"] for e in loose} == {"pa@trail.com", "spa@trail.com"}               # the looser search still exists
    assert client.get("/audit-logs/?email=nobody@trail.com", headers=auth["super"]).json() == []


def test_person_filter_combines_with_the_others_and_shows_when(client, auth):
    write("combo@trail.com", "CREATE_INCIDENT", n=2)
    write("combo@trail.com", "UPDATE_SITE")
    today = date.today().isoformat()
    r = client.get(f"/audit-logs/?email=combo@trail.com&action=CREATE_INCIDENT&start={today}&end={today}", headers=auth["super"])
    rows = r.json()
    assert len(rows) == 2 and r.headers["x-total-count"] == "2"
    assert all(e["timestamp"] and e["action"] == "CREATE_INCIDENT" for e in rows)   # every entry says when
    ids = [e["id"] for e in rows]
    assert ids == sorted(ids, reverse=True)                                         # newest first


# ─── the people list ────────────────────────────────────────────────────────

def test_people_list_has_everyone_with_names_roles_and_status(client, auth):
    make_user("active@trail.com", "site_manager", "Tendai Moyo")
    make_user("off@trail.com", "she_team", None, active=False)
    write("ghost1@trail.com", "CREATE_INCIDENT")                 # in the log but has no account (e.g. deleted)
    people = {p["email"]: p for p in client.get("/audit-logs/facets", headers=auth["super"]).json()["users"]}
    assert people["active@trail.com"] == {"email": "active@trail.com", "name": "Tendai Moyo", "role": "site_manager", "status": "active"}
    assert people["off@trail.com"]["status"] == "inactive"
    assert people["ghost1@trail.com"]["status"] == "removed"       # still selectable: their history is kept
    assert "super@x.com" in people                                  # people with no activity yet are listed too
    names = [(p["name"] or p["email"]).lower() for p in client.get("/audit-logs/facets", headers=auth["super"]).json()["users"]]
    assert names == sorted(names)


# ─── the per-person summary ─────────────────────────────────────────────────

def test_person_summary(client, auth):
    write("sum@trail.com", "CREATE_INCIDENT", n=3)
    write("sum@trail.com", "UPDATE_SITE", n=1)
    write("sum@trail.com", "LOGIN", n=2)
    write("sum@trail.com", "LOGIN_FAILED", n=1)
    s = client.get("/audit-logs/person?email=sum@trail.com", headers=auth["super"]).json()
    assert s["total"] == 7 and s["failed_sign_ins"] == 1
    assert s["first_at"] and s["last_at"] and s["last_sign_in_at"]
    assert s["by_activity"][0] == {"action": "CREATE_INCIDENT", "label": "Incident logged", "count": 3}
    assert {a["label"] for a in s["by_activity"]} >= {"Signed in", "Failed sign-in attempt", "Site updated"}
    empty = client.get("/audit-logs/person?email=super@x.com&", headers=auth["super"]).json()
    assert empty["status"] == "active" and empty["role"] == "super_admin"
    unknown = client.get("/audit-logs/person?email=never@trail.com", headers=auth["super"]).json()
    assert unknown["total"] == 0 and unknown["first_at"] is None and unknown["status"] == "unknown"


def test_person_summary_is_super_admin_only(client, auth):
    assert client.get("/audit-logs/person?email=a@b.com").status_code == 401
    for who in ("admin", "she", "mgr"):
        assert client.get("/audit-logs/person?email=a@b.com", headers=auth[who]).status_code == 403


def test_export_is_gone(client, auth):
    assert client.get("/audit-logs/export", headers=auth["super"]).status_code in (404, 422)


# ─── what gets recorded ─────────────────────────────────────────────────────

def test_sign_ins_are_recorded(client):
    make_user("login@trail.com", "she_team", "Login Person")
    ok = client.post("/auth/login", data={"username": "login@trail.com", "password": PW})
    assert ok.status_code == 200
    entry = logs(user_email="login@trail.com", action="LOGIN")[-1]
    assert entry.resource == "auth" and entry.user_role == "she_team" and entry.ip_address

    bad = client.post("/auth/login", data={"username": "login@trail.com", "password": "wrong-pass-123"})
    assert bad.status_code == 401
    failed = logs(user_email="login@trail.com", action="LOGIN_FAILED")[-1]
    assert failed.details == "Wrong password" and failed.user_role == "she_team"
    assert "wrong-pass-123" not in (failed.details or "")                     # the typed password is never stored

    client.post("/auth/login", data={"username": "ghost-typo@x.com", "password": "whatever-123"})
    unknown = logs(user_email="ghost-typo@x.com", action="LOGIN_FAILED")[-1]
    assert unknown.user_role == "unknown" and unknown.details == "No account with this email"


def test_deactivated_account_attempts_are_recorded(client):
    make_user("frozen@trail.com", "she_team", None, active=False)
    assert client.post("/auth/login", data={"username": "frozen@trail.com", "password": PW}).status_code == 403
    assert logs(user_email="frozen@trail.com", action="LOGIN_FAILED")[-1].details == "Account is deactivated"


def test_very_long_typed_emails_cannot_bloat_the_log(client):
    client.post("/auth/login", data={"username": "x" * 5000 + "@y.com", "password": "pass-1234"})
    db = SessionLocal()
    longest = max(len(e.user_email) for e in db.query(AuditLog).filter(AuditLog.action == "LOGIN_FAILED"))
    db.close()
    assert longest <= 254
    db = SessionLocal()
    db.query(AuditLog).filter(AuditLog.user_email.like("xxxx%")).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_inspections_scorecards_and_registrations_are_recorded(client, auth):
    mgr = auth["mgr"]
    r = client.post("/inspections/", data={"site_id": 1, "inspection_date": date.today().isoformat(), "checklist_score": 80, "she_file_score": 60},
                    headers=mgr)
    assert r.status_code == 200
    iid = r.json()["id"]
    assert "overall score 70.0%" in logs(action="CREATE_INSPECTION", resource_id=iid)[-1].details
    assert client.put(f"/inspections/{iid}", json={"comments": "edited"}, headers=mgr).status_code == 200
    assert logs(action="UPDATE_INSPECTION", resource_id=iid)
    assert client.delete(f"/inspections/{iid}", headers=auth["she"]).status_code == 200
    assert logs(action="DELETE_INSPECTION", resource_id=iid)

    sc = client.post("/scorecard/", json={"site_id": 1, "items": [{"requirement_ref": "FWA-1", "score": 4}]}, headers=mgr)
    assert sc.status_code == 201
    sid = sc.json()["id"]
    assert logs(action="CREATE_SCORECARD", resource_id=sid)[-1].user_email == "mgr@x.com"
    assert client.delete(f"/scorecard/{sid}", headers=auth["admin"]).status_code == 204
    assert logs(action="DELETE_SCORECARD", resource_id=sid)

    reg = client.post("/auth/register", json={"email": "reg@trail.com", "password": PW, "role": "she_team"}, headers=auth["admin"])
    assert reg.status_code == 200
    assert logs(action="CREATE_USER", resource_id=reg.json()["id"])[-1].user_email == "admin@x.com"
