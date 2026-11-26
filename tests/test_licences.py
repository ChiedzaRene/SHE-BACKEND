"""Site licences: register per site and type, renewals keep history, reminders 3 months and 1 month before."""
from datetime import date, timedelta

from database import SessionLocal
from models.notification import Notification
from services import licences as svc

TODAY = date.today()  # recording a licence checks reminders against the real date, so the test must too


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


def test_the_licence_types(client):
    types = client.get("/licences/types").json()
    assert [t["name"] for t in types] == [
        "Council shop licence", "Fire brigade licence", "EMA septic tank waste discharge licence",
        "EMA air emission licence", "Hazardous substance storage and sale licence",
        "Council trade effluent licence", "Environmental Impact Assessment (EIA) licence"]
    eia = types[-1]
    assert eia["valid_months"] == 3 and eia["she_only"] is True and eia["reminder_days"] == [30, 14]
    assert types[0]["reminder_days"] == [90, 30] and types[0]["she_only"] is False


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


def test_eia_licences_are_quarterly_and_uploaded_by_the_she_team(client, auth):
    # every site has one, shown as not recorded until the SHE team uploads it
    reg = client.get("/licences/", headers=auth["mgr"]).json()
    cell = next(c for c in reg["sites"][0]["licences"] if c["licence_type"] == "ema_eia")
    assert cell["status"] == "missing" and cell["can_edit"] is False and cell["valid_months"] == 3

    issued = TODAY - timedelta(days=10)
    data = {"site_id": "1", "licence_type": "ema_eia", "issue_date": issued.isoformat()}
    refused = client.post("/licences/", data=data, headers=auth["mgr"])
    assert refused.status_code == 403 and "SHE team" in refused.json()["detail"]
    lic = client.post("/licences/", data=data, headers=auth["she"])
    assert lic.status_code == 201, lic.text
    lic = lic.json()
    from services.fire_inspections import add_months
    assert lic["expiry_date"] == add_months(issued, 3).isoformat()      # filled in: three months on
    assert client.put(f"/licences/{lic['id']}", data={"notes": "x"}, headers=auth["mgr"]).status_code == 403
    she_cell = next(c for c in client.get("/licences/", headers=auth["she"]).json()["sites"][0]["licences"]
                    if c["licence_type"] == "ema_eia")
    assert she_cell["can_edit"] is True and she_cell["current"]["id"] == lic["id"]
    # other licence types still need their expiry date
    assert client.post("/licences/", data={"site_id": "1", "licence_type": "fire_brigade"},
                       headers=auth["she"]).status_code == 422


def test_eia_reminders_a_month_and_two_weeks_before_then_expired():
    assert svc.status_of(TODAY + timedelta(days=60), TODAY, "ema_eia") == "valid"      # not "due in 3 months"
    assert svc.status_of(TODAY + timedelta(days=30), TODAY, "ema_eia") == "due_3_months"
    assert svc.status_of(TODAY + timedelta(days=14), TODAY, "ema_eia") == "due_1_month"
    assert svc.status_label("due_3_months", "ema_eia") == "Due within a month"
    assert svc.status_label("due_1_month", "ema_eia") == "Due within 2 weeks"
    assert svc.status_label("due_3_months") == "Due within 3 months"

    from models.site_licence import SiteLicence
    db = SessionLocal()
    try:
        expiry = TODAY + timedelta(days=200)
        lic = SiteLicence(site_id=1, licence_type="ema_eia", expiry_date=expiry, created_by=1)
        db.add(lic)
        db.commit()
        before = len(_notes(4, "licence_due"))
        svc.send_reminders(db, expiry - timedelta(days=60))                    # two months left: nothing
        assert len(_notes(4, "licence_due")) == before
        svc.send_reminders(db, expiry - timedelta(days=30))
        assert "Environmental Impact Assessment (EIA) licence for Site A is due in a month" in _notes(4, "licence_due")
        svc.send_reminders(db, expiry - timedelta(days=20))                    # not again
        assert len(_notes(4, "licence_due")) == before + 1
        svc.send_reminders(db, expiry - timedelta(days=14))
        assert any("EIA) licence for Site A is due in 14 days" in t for t in _notes(4, "licence_due"))
        svc.send_reminders(db, expiry + timedelta(days=1))
        assert any("EIA" in t and "expired" in t for t in _notes(4, "licence_expired"))
        db.delete(lic)
        db.commit()
    finally:
        db.close()
