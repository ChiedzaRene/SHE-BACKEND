"""Weekly toolbox talks: Monday–Tuesday window, completion rate, missed-week alerts; SHE trainings with documents."""
from datetime import date

import pytest

import routers.safety_talks as talks_router
from database import SessionLocal
from models.app_setting import AppSetting
from models.notification import Notification
from models.safety_talk import SafetyTalk, SafetyTalkMiss
from models.site import Site
from services import safety_talks as svc

PDF = b"%PDF-1.4\n%%EOF\n"
MON, TUE, WED = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)


@pytest.fixture(autouse=True)
def tracking_from_september(client):
    db = SessionLocal()
    row = db.query(AppSetting).filter(AppSetting.key == svc.START_KEY).first()
    if row:
        row.value = "2026-08-31"
    else:
        db.add(AppSetting(key=svc.START_KEY, value="2026-08-31"))
    db.commit()
    db.close()


def _on(monkeypatch, day):
    monkeypatch.setattr(talks_router, "local_today", lambda: day)


def _submit(client, headers, title="Working at heights", attendees=12, name="register.pdf", content=PDF):
    return client.post("/safety-talks/", data={"title": title, "attendees": str(attendees)},
                       files={"file": (name, content, "application/pdf")}, headers=headers)


def test_window_rules():
    assert svc.open_week(MON) == MON and svc.open_week(TUE) == MON and svc.open_week(WED) is None
    assert svc.open_week(date(2026, 9, 20)) is None                      # Sunday
    assert svc.next_open(WED) == date(2026, 9, 21) and svc.next_open(MON) == MON
    d = svc.deadline_of(MON)
    assert (d.date(), d.hour, d.minute) == (TUE, 23, 59)
    assert not svc.is_closed(MON, TUE) and svc.is_closed(MON, WED)


def test_only_the_site_manager_submits_and_only_on_monday_or_tuesday(client, auth, monkeypatch):
    _on(monkeypatch, WED)
    closed = _submit(client, auth["mgr"])
    assert closed.status_code == 409 and "Monday and Tuesday" in closed.json()["detail"]
    _on(monkeypatch, TUE)
    assert _submit(client, auth["she"]).status_code == 403
    first = _submit(client, auth["mgr"], title="Fire extinguishers")
    assert first.status_code == 201, first.text
    assert first.json()["week_of"] == MON.isoformat() and first.json()["site_name"] == "Site A"
    # resubmitting before the deadline replaces the week's talk
    again = _submit(client, auth["mgr"], title="Fire extinguishers (corrected)", attendees=14)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    db = SessionLocal()
    assert db.query(SafetyTalk).filter(SafetyTalk.site_id == 1, SafetyTalk.week_of == MON).count() == 1
    db.close()
    assert _submit(client, auth["mgr"], name="talk.html", content=b"<p>").status_code == 400
    bad = client.post("/safety-talks/", data={"title": "x", "attendees": "0"},
                      files={"file": ("a.pdf", PDF, "application/pdf")}, headers=auth["mgr"])
    assert bad.status_code == 422


def test_completion_rate_counts_closed_weeks_and_early_submissions():
    db = SessionLocal()
    site = db.query(Site).filter(Site.id == 1).first()
    # weeks of 31 Aug, 7 Sep (missed), 14 Sep (done above) – on Wednesday 16 Sep
    db.add(SafetyTalk(site_id=1, week_of=date(2026, 8, 31), title="PPE", attendees=9, filename="a.pdf",
                      content_type="application/pdf", size=3, data=b"pdf", submitted_by=3))
    db.commit()
    st = svc.weeks_status(db, [site], date(2026, 8, 1), date(2026, 10, 1), WED)[1]
    assert (st["due"], st["done"], st["rate"]) == (3, 2, 66.7)
    assert st["missed_weeks"] == ["2026-09-07"]
    # on Monday 21 Sep the new week is open: it isn't due yet, so the rate doesn't drop
    st = svc.weeks_status(db, [site], date(2026, 8, 1), date(2026, 10, 1), date(2026, 9, 21))[1]
    assert st["due"] == 3 and st["this_week_open"] and not st["this_week_done"]
    db.close()


def test_missed_weeks_are_reported_to_the_she_team_once(client, auth):
    db = SessionLocal()
    try:
        told = svc.record_missed(db, WED)
        assert told >= 1
        assert db.query(SafetyTalkMiss).filter(SafetyTalkMiss.site_id == 1, SafetyTalkMiss.week_of == date(2026, 9, 7)).count() == 1
        assert svc.record_missed(db, WED) == 0                       # not twice
        she_notes = db.query(Notification).filter(Notification.user_id == 4, Notification.kind == "talk_missed").all()
        assert any("Site A" in n.title and "7 Sep" in n.title for n in she_notes)
        mgr_notes = db.query(Notification).filter(Notification.user_id == 3, Notification.kind == "talk_missed").all()
        assert mgr_notes
        # a week with a talk is never reported
        assert not any("14 Sep" in n.title and "Site A" in n.title for n in she_notes)
    finally:
        db.close()


def test_overview_filters_by_site_region_and_period(client, auth, monkeypatch):
    db = SessionLocal()
    db.query(Site).filter(Site.id == 1).update({Site.region: "Harare"})
    db.query(Site).filter(Site.id == 2).update({Site.region: "Bulawayo"})
    db.commit()
    db.close()
    _on(monkeypatch, WED)
    o = client.get("/safety-talks/overview", params={"period": "3m"}, headers=auth["she"]).json()
    assert "Harare" in o["regions"] and "Bulawayo" in o["regions"]
    names = {r["name"] for r in o["sites"]}
    assert {"Site A", "Site B"} <= names
    assert any(m["name"] == "Site B" for m in o["missed"])
    assert any(t["title"] == "Fire extinguishers (corrected)" and t["attendees"] == 14 for t in o["talks"])
    harare = client.get("/safety-talks/overview", params={"period": "3m", "region": "Harare"}, headers=auth["she"]).json()
    assert [r["name"] for r in harare["sites"]] == ["Site A"]
    one = client.get("/safety-talks/overview", params={"period": "3m", "site_id": 2}, headers=auth["she"]).json()
    assert [r["name"] for r in one["sites"]] == ["Site B"] and one["talks"] == []
    # a manager only ever sees their own site
    mine = client.get("/safety-talks/overview", params={"period": "3m", "site_id": 2}, headers=auth["mgr"]).json()
    assert [r["site_id"] for r in mine["sites"]] == [1]
    assert client.get("/safety-talks/overview", params={"period": "forever"}, headers=auth["she"]).status_code == 422


def test_talk_documents_are_visible_to_the_site_and_the_she_team(client, auth, monkeypatch):
    _on(monkeypatch, WED)
    talk = client.get("/safety-talks/overview", params={"period": "3m", "site_id": 1}, headers=auth["she"]).json()["talks"][0]
    assert client.get(f"/safety-talks/{talk['id']}/download", headers=auth["she"]).content.startswith(b"%PDF")
    assert client.get(f"/safety-talks/{talk['id']}/view", headers=auth["mgr"]).status_code == 200


def test_current_week_for_the_manager(client, auth, monkeypatch):
    _on(monkeypatch, TUE)
    cur = client.get("/safety-talks/current", headers=auth["mgr"]).json()
    assert cur["open"] is True and cur["week_of"] == MON.isoformat() and cur["talk"]["title"].startswith("Fire")
    assert cur["deadline"].startswith("2026-09-15T23:59:59")
    _on(monkeypatch, WED)
    cur = client.get("/safety-talks/current", headers=auth["mgr"]).json()
    assert cur["open"] is False and cur["next_open"] == "2026-09-21"
    assert cur["cumulative"]["due"] >= 3


def test_she_team_records_a_training_with_its_document(client, auth):
    form = {"site_id": "1", "date": "2026-09-10", "training_module": "Fire fighting", "trainer_name": "Rudo Chikore",
            "personnel": "Tendai Moyo, Farai Moyo, Chipo Dube", "trained_employees": "3", "type": "Fire safety"}
    doc = {"file": ("attendance.pdf", PDF, "application/pdf")}
    assert client.post("/trainings/record", data=form, files=doc, headers=auth["mgr"]).status_code == 403
    assert client.post("/trainings/record", data=form, headers=auth["she"]).status_code == 422      # document needed
    r = client.post("/trainings/record", data=form, files=doc, headers=auth["she"])
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["has_document"] and t["document_name"] == "attendance.pdf" and t["trainer_name"] == "Rudo Chikore"
    assert t["trained_employees"] == 3 and t["date"].startswith("2026-09-10")
    assert client.get(f"/trainings/{t['id']}/document", headers=auth["mgr"]).content == PDF   # the site's manager
    listed = client.get("/trainings/", headers=auth["mgr"]).json()
    assert any(x["id"] == t["id"] and x["document_viewable"] for x in listed)
    future = client.post("/trainings/record", data={**form, "date": "2099-01-01"}, files=doc, headers=auth["she"])
    assert future.status_code == 422
    other = client.post("/trainings/record", data={**form, "site_id": "2"}, files=doc, headers=auth["she"]).json()
    assert client.get(f"/trainings/{other['id']}/document", headers=auth["mgr"]).status_code == 403


def test_dashboard_shows_talk_completion_and_filters_by_region(client, auth):
    s = client.get("/dashboard/summary", params={"period": "12m"}, headers=auth["she"]).json()
    assert "talks_rate" in s["current"]["totals"] and "Harare" in s["regions"]
    assert all("talks_rate" in r for r in s["current"]["sites"])
    harare = client.get("/dashboard/summary", params={"period": "12m", "region": "Harare"}, headers=auth["she"]).json()
    assert [r["name"] for r in harare["current"]["sites"]] == ["Site A"]
    assert client.get("/dashboard/summary", params={"period": "3m"}, headers=auth["she"]).status_code == 200


def test_sites_have_a_region(client, auth):
    r = client.post("/sites/", json={"name": "Region Test", "address": "1 Road", "region": "  Masvingo  "},
                    headers=auth["admin"])
    assert r.status_code == 201 and r.json()["region"] == "Masvingo"


def test_a_site_added_on_tuesday_counts_that_weeks_talk():
    site = Site(id=77, name="Tuesday Site", address="x", talks_from=TUE)
    assert svc.site_start(site, date(2026, 8, 31)) == MON
    added_wednesday = Site(id=78, name="Wednesday Site", address="x", talks_from=WED)
    assert svc.site_start(added_wednesday, date(2026, 8, 31)) == TUE   # this week's window had closed
