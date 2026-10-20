"""Site licences: register per site and type, renewals keep history, reminders 3 months and 1 month before."""
from datetime import date, timedelta

from database import SessionLocal
from models.notification import Notification
from services import licences as svc

TODAY = date(2026, 10, 20)


def _record(client, headers, licence_type="fire_brigade", expiry=None, site_id=1, **extra):
    data = {"site_id": str(site_id), "licence_type": licence_type,
            "expiry_date": (expiry or TODAY + timedelta(days=200)).isoformat(), **extra}
    return client.post("/licences/", data=data, headers=headers)


def _notes(user_id, kind):
    db = SessionLocal()
    try:
        return [n.title for n in db.query(Notification).filter(Notification.user_id == user_id, Notification.kind == kind)]
    finally:
        db.close()


def test_the_six_licence_types(client):
    names = [t["name"] for t in client.get("/licences/types").json()]
    assert names == ["Council shop licence", "Fire brigade licence", "EMA septic tank waste discharge licence",
                     "EMA air emission licence", "Hazardous substance storage and sale licence",
                     "Council trade effluent licence"]


def test_status_bands():
    assert svc.status_of(TODAY + timedelta(days=120), TODAY) == "valid"
    assert svc.status_of(TODAY + timedelta(days=90), TODAY) == "due_3_months"
    assert svc.status_of(TODAY + timedelta(days=30), TODAY) == "due_1_month"
    assert svc.status_of(TODAY - timedelta(days=1), TODAY) == "expired"
    assert svc.status_of(None, TODAY) == "missing"


def test_recording_and_renewing_keeps_history(client, auth):
    r = _record(client, auth["she"], licence_number="FB-001", amount="150",
                expiry=date.today() + timedelta(days=200))
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Fire brigade licence" and r.json()["status"] == "valid"
    assert _record(client, auth["mgr"], site_id=2).status_code == 403          # not their site
    assert _record(client, auth["she"], licence_type="driving").status_code == 422
    renewed = _record(client, auth["mgr"], licence_number="FB-002", expiry=date.today() + timedelta(days=565),
                      ).json()                                                   # the site records its renewal
    reg = client.get("/licences/", params={"site_id": 1}, headers=auth["she"]).json()
    site = reg["sites"][0]
    fire = next(c for c in site["licences"] if c["licence_type"] == "fire_brigade")
    assert fire["current"]["id"] == renewed["id"] and fire["current"]["licence_number"] == "FB-002"
    assert [h["licence_number"] for h in fire["history"]] == ["FB-001"]
    assert next(c for c in site["licences"] if c["licence_type"] == "ema_air")["status"] == "missing"
    # a site manager only sees their own site
    assert [s["site_id"] for s in client.get("/licences/", headers=auth["mgr"]).json()["sites"]] == [1]


def test_certificate_upload(client, auth):
    r = client.post("/licences/", data={"site_id": "1", "licence_type": "council_shop",
                                        "expiry_date": (date.today() + timedelta(days=300)).isoformat()},
                    files={"file": ("shop-licence.pdf", b"%PDF-1.4", "application/pdf")}, headers=auth["she"])
    lic = r.json()
    assert lic["document_name"] == "shop-licence.pdf" and lic["document_viewable"]
    assert client.get(f"/licences/{lic['id']}/document", headers=auth["mgr"]).content == b"%PDF-1.4"
    assert client.get(f"/licences/{lic['id']}/document", params={"download": True},
                      headers=auth["mgr"]).headers["content-disposition"].startswith("attachment")


def test_reminders_three_months_and_one_month_before_then_expired(client, auth):
    lic = _record(client, auth["she"], licence_type="ema_septic", expiry=TODAY + timedelta(days=100)).json()
    db = SessionLocal()
    try:
        svc.send_reminders(db, TODAY)                                           # 100 days left: nothing yet
        before = len(_notes(4, "licence_due"))
        svc.send_reminders(db, TODAY + timedelta(days=12))                      # 88 days left
        svc.send_reminders(db, TODAY + timedelta(days=13))                      # not again
        she = _notes(4, "licence_due")
        assert len(she) == before + 1 and "EMA septic tank waste discharge licence for Site A is due in 3 months" in she
        assert any("EMA septic" in t for t in _notes(3, "licence_due"))        # the site's manager too
        svc.send_reminders(db, TODAY + timedelta(days=72))                      # 28 days left
        assert any("EMA septic tank waste discharge licence for Site A is due in 28 days" in t for t in _notes(4, "licence_due"))
        svc.send_reminders(db, TODAY + timedelta(days=101))
        assert any("EMA septic" in t and "expired" in t for t in _notes(4, "licence_expired"))
    finally:
        db.close()
    assert lic["id"]


def test_correcting_the_due_date_restarts_reminders(client, auth):
    lic = _record(client, auth["she"], licence_type="ema_air", expiry=date.today() + timedelta(days=20)).json()
    assert lic["status"] == "due_1_month"
    assert any("EMA air emission licence for Site A is due in" in t for t in _notes(3, "licence_due"))
    fixed = client.put(f"/licences/{lic['id']}", data={"expiry_date": (date.today() + timedelta(days=400)).isoformat()},
                       headers=auth["she"]).json()
    assert fixed["status"] == "valid"
    assert client.delete(f"/licences/{lic['id']}", headers=auth["mgr"]).status_code == 403
    assert client.delete(f"/licences/{lic['id']}", headers=auth["she"]).status_code == 200
