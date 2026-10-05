from datetime import date, datetime

import pytest

from database import SessionLocal
from models.audit import Audit
from models.corrective_action import CorrectiveAction
from models.incident import Incident
from models.notification import Notification
from models.site_hours import SiteHours
from models.user import User
from services.auth_services import hash_password
from services.safety_metrics import compute_range


@pytest.fixture(autouse=True)
def clean(client):
    """Everything these tests create is removed afterwards so other tests see the original data."""
    db = SessionLocal()
    before = {
        "incidents": {i for (i,) in db.query(Incident.id).all()},
        "actions": {i for (i,) in db.query(CorrectiveAction.id).all()},
        "audits": {i for (i,) in db.query(Audit.id).all()},
    }
    db.close()
    yield
    db = SessionLocal()
    db.query(Notification).delete()
    db.query(CorrectiveAction).filter(CorrectiveAction.id.notin_(before["actions"] or {0})).delete(synchronize_session=False)
    db.query(Audit).filter(Audit.id.notin_(before["audits"] or {0})).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.id.notin_(before["incidents"] or {0})).delete(synchronize_session=False)
    db.query(SiteHours).filter(SiteHours.site_id == 2, SiteHours.period == date(2020, 1, 1)).delete()
    db.commit()
    db.close()


def inbox(client, headers, **params):
    r = client.get("/notifications/", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def log_injury(client, auth, **extra):
    body = {"site_id": 1, "type": "injury", "severity": "high", "description": "Slipped at pump 3 & hurt wrist",
            "injured_person": "Farai Moyo", **extra}
    r = client.post("/incidents/", json=body, headers=auth["mgr"])
    assert r.status_code == 200, r.text
    return r.json()


def test_injured_person_is_saved_and_shown(client, auth):
    incident = log_injury(client, auth)
    assert incident["injured_person"] == "Farai Moyo"
    again = client.get(f"/incidents/{incident['id']}", headers=auth["admin"]).json()
    assert again["injured_person"] == "Farai Moyo"
    edited = client.put(f"/incidents/{incident['id']}", json={"injured_person": "Farai T. Moyo"}, headers=auth["admin"])
    assert edited.json()["injured_person"] == "Farai T. Moyo"
    register = client.get("/reports/incidents", headers=auth["admin"]).json()
    table = register["tables"][0]
    col = table["columns"].index("Injured person")
    assert any(row[col] == "Farai T. Moyo" for row in table["rows"])


def test_injured_person_is_optional_and_limited(client, auth):
    r = client.post("/incidents/", json={"site_id": 1, "type": "spill", "severity": "low",
                                         "description": "Small diesel spill"}, headers=auth["mgr"])
    assert r.status_code == 200 and r.json()["injured_person"] is None
    too_long = client.post("/incidents/", json={"site_id": 1, "type": "injury", "severity": "low",
                                                "description": "Cut finger", "injured_person": "x" * 151},
                           headers=auth["mgr"])
    assert too_long.status_code == 422


def test_new_incident_notifies_the_team_and_site_manager_but_not_the_person_who_logged_it(client, auth):
    incident = log_injury(client, auth)
    for who in ("admin", "super", "she"):
        items = inbox(client, auth[who])["items"]
        assert items and items[0]["kind"] == "incident_recorded"
        assert items[0]["resource"] == "incidents" and items[0]["resource_id"] == incident["id"]
        assert "Farai Moyo" in items[0]["title"] and "Site A" in items[0]["title"]
        assert items[0]["link"] == "/incidents" and items[0]["read_at"] is None
    assert inbox(client, auth["mgr"])["items"] == []

    # an incident logged by the SHE team reaches the site's manager
    client.post("/incidents/", json={"site_id": 1, "type": "fire", "severity": "low", "description": "Bin fire out"},
                headers=auth["she"])
    assert inbox(client, auth["mgr"])["items"][0]["kind"] == "incident_recorded"


def test_corrective_action_assignee_is_notified_by_name_or_email(client, auth):
    r = client.post("/corrective-actions/", json={"site_id": 1, "assigned_to": "manager", "action_taken": "Fix drain",
                                                  "due_date": "2030-01-31T00:00:00"}, headers=auth["admin"])
    assert r.status_code == 200, r.text
    mine = inbox(client, auth["mgr"])["items"]
    assert mine[0]["kind"] == "action_assigned" and "assigned to you" in mine[0]["title"]
    assert "Fix drain" in mine[0]["message"] and "31 Jan 2030" in mine[0]["message"]

    client.post("/corrective-actions/", json={"site_id": 1, "assigned_to": "MGR@x.com", "action_taken": "Replace mat"},
                headers=auth["admin"])
    assert inbox(client, auth["mgr"])["items"][0]["message"].endswith("Replace mat.")

    # a contractor without an account: nobody is "assigned", but the site manager still hears about it
    client.post("/corrective-actions/", json={"site_id": 1, "assigned_to": "Acme Plumbing", "action_taken": "Fix tap"},
                headers=auth["admin"])
    latest = inbox(client, auth["mgr"])["items"][0]
    assert latest["kind"] == "action_created" and "Acme Plumbing" in latest["title"]


def test_reassigning_an_action_notifies_the_new_person(client, auth):
    action = client.post("/corrective-actions/", json={"site_id": 1, "assigned_to": "Acme Plumbing",
                                                       "action_taken": "Fix tap"}, headers=auth["admin"]).json()
    client.post("/notifications/read", json={"all": True}, headers=auth["mgr"])
    client.put(f"/corrective-actions/{action['id']}", json={"assigned_to": "Manager"}, headers=auth["admin"])
    assert inbox(client, auth["mgr"], unread_only=True)["items"][0]["kind"] == "action_assigned"
    # saving without changing the assignee does not notify again
    client.put(f"/corrective-actions/{action['id']}", json={"priority": "high"}, headers=auth["admin"])
    assert inbox(client, auth["mgr"])["unread"] == 1


def test_new_audit_notifies_site_manager_and_team(client, auth):
    r = client.post("/audits/", json={"site_id": 1, "criteria": "Fire safety", "score": 82, "status": "open"},
                    headers=auth["she"])
    assert r.status_code == 200, r.text
    for who in ("mgr", "admin", "super"):
        item = inbox(client, auth[who])["items"][0]
        assert item["kind"] == "audit_recorded" and "Fire safety" in item["title"] and "82%" in item["message"]
    assert inbox(client, auth["she"])["items"] == []


def test_inbox_is_newest_first_counts_unread_and_marks_read(client, auth):
    log_injury(client, auth)
    client.post("/audits/", json={"site_id": 1, "criteria": "Housekeeping", "score": 90}, headers=auth["mgr"])
    data = inbox(client, auth["admin"])
    assert [i["kind"] for i in data["items"][:2]] == ["audit_recorded", "incident_recorded"]
    assert data["unread"] == 2

    assert client.post("/notifications/read", json={"resource": "incidents"}, headers=auth["admin"]).json()["marked"] == 1
    assert inbox(client, auth["admin"])["unread"] == 1
    assert len(inbox(client, auth["admin"], resource="audits", unread_only=True)["items"]) == 1
    client.post("/notifications/read", json={"all": True}, headers=auth["admin"])
    assert inbox(client, auth["admin"])["unread"] == 0
    assert client.post("/notifications/read", json={}, headers=auth["admin"]).json()["marked"] == 0


def test_people_only_see_and_mark_their_own(client, auth):
    log_injury(client, auth)
    admin_ids = [i["id"] for i in inbox(client, auth["admin"])["items"]]
    assert client.post("/notifications/read", json={"ids": admin_ids}, headers=auth["she"]).json()["marked"] == 0
    assert inbox(client, auth["admin"])["unread"] == 1
    assert client.get("/notifications/").status_code == 401


def test_account_changes_and_password_resets_are_told_to_the_person(client, auth):
    db = SessionLocal()
    person = User(email="notify-me@x.com", password=hash_password("Temp-pass-123"), role="she_team", full_name="Tari")
    db.add(person)
    db.commit()
    pid = person.id
    db.close()
    try:
        r = client.put(f"/users/{pid}", json={"role": "site_manager", "site_id": 1, "password": "Reset-pass-456"},
                       headers=auth["admin"])
        assert r.status_code == 200, r.text
        db = SessionLocal()
        kinds = {n.kind: n for n in db.query(Notification).filter(Notification.user_id == pid).all()}
        db.close()
        assert set(kinds) == {"password_reset", "account_updated"}
        assert "Site manager" in kinds["account_updated"].message and "Site A" in kinds["account_updated"].message
    finally:
        db = SessionLocal()
        db.query(Notification).filter(Notification.user_id == pid).delete()
        db.query(User).filter(User.id == pid).delete()
        db.commit()
        db.close()


def test_injuries_in_months_without_hours_are_reported_not_hidden():
    db = SessionLocal()
    db.add(SiteHours(site_id=2, period=date(2020, 1, 1), hours_worked=10000, entered_by=1))
    db.add(Incident(site_id=2, user_id=1, type="injury", description="d", severity="low",
                    occurred_at=datetime(2020, 2, 10)))
    db.commit()
    try:
        stats = compute_range(db, [2], date(2020, 1, 1), date(2020, 3, 1))[2]
        assert stats["hours_reported"] and stats["trir"] == 0.0     # January has hours, no injuries
        assert stats["uncounted_injuries"] == 1                     # the February injury has no hours yet
        assert stats["months_missing_hours"] == ["2020-02"]
    finally:
        db.query(Incident).filter(Incident.occurred_at == datetime(2020, 2, 10)).delete()
        db.commit()
        db.close()


def test_staff_directory_lists_active_people_for_assigning(client, auth):
    r = client.get("/users/directory", headers=auth["mgr"])
    assert r.status_code == 200
    assert {"name": "Manager", "email": "mgr@x.com"} in r.json()
    assert client.get("/users/directory").status_code == 401


def test_mark_all_or_some_as_unread_again(client, auth):
    log_injury(client, auth)
    client.post("/audits/", json={"site_id": 1, "criteria": "Housekeeping", "score": 90}, headers=auth["mgr"])
    client.post("/notifications/read", json={"all": True}, headers=auth["admin"])
    assert inbox(client, auth["admin"])["unread"] == 0

    ids = [i["id"] for i in inbox(client, auth["admin"])["items"]]
    assert client.post("/notifications/unread", json={"ids": ids[:1]}, headers=auth["admin"]).json()["marked"] == 1
    assert inbox(client, auth["admin"])["unread"] == 1
    assert client.post("/notifications/unread", json={"all": True}, headers=auth["admin"]).json()["marked"] == 1
    data = inbox(client, auth["admin"])
    assert data["unread"] == 2 and all(i["read_at"] is None for i in data["items"])
    # someone else's can't be touched, and an empty request does nothing
    client.post("/notifications/read", json={"all": True}, headers=auth["admin"])
    assert client.post("/notifications/unread", json={"ids": ids}, headers=auth["she"]).json()["marked"] == 0
    assert client.post("/notifications/unread", json={}, headers=auth["admin"]).json()["marked"] == 0


def test_opened_notifications_disappear_24_hours_after_opening(client, auth):
    from datetime import timedelta, timezone
    from services.retention import purge_old_notifications

    log_injury(client, auth)
    client.post("/audits/", json={"site_id": 1, "criteria": "Housekeeping", "score": 90}, headers=auth["mgr"])
    items = inbox(client, auth["admin"])["items"]
    opened_long_ago, opened_recently = items[0]["id"], items[1]["id"]
    client.post("/notifications/read", json={"ids": [opened_recently]}, headers=auth["admin"])

    db = SessionLocal()
    old = db.get(Notification, opened_long_ago)
    old.read_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()
    db.close()

    shown = {i["id"] for i in inbox(client, auth["admin"])["items"]}
    assert opened_long_ago not in shown and opened_recently in shown   # hidden straight away
    # and it can't be brought back by "mark all as unread"
    client.post("/notifications/unread", json={"all": True}, headers=auth["admin"])
    assert opened_long_ago not in {i["id"] for i in inbox(client, auth["admin"])["items"]}

    db = SessionLocal()
    assert purge_old_notifications(db) >= 1                              # then deleted by housekeeping
    assert db.get(Notification, opened_long_ago) is None
    assert db.get(Notification, opened_recently) is not None
    db.close()


def test_unread_notifications_are_never_removed_for_age_under_90_days(client, auth):
    from datetime import timedelta, timezone
    from services.retention import purge_old_notifications

    log_injury(client, auth)
    nid = inbox(client, auth["admin"])["items"][0]["id"]
    db = SessionLocal()
    n = db.get(Notification, nid)
    n.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()
    purge_old_notifications(db)
    assert db.get(Notification, nid) is not None
    db.close()
    assert nid in {i["id"] for i in inbox(client, auth["admin"])["items"]}
