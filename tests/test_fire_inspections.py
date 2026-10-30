"""Fire equipment inspections sent by the sites (fortnightly checklist; six-monthly service and refill),
the two-week reminder before a service is due, and audit inspection reports."""
import json
from datetime import date, timedelta

from database import SessionLocal
from models.fire_inspection import FireInspection
from models.notification import Notification
from models.user import User
from services.fire_inspections import ITEMS, add_months, send_reminders

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _all_answers(result="C"):
    return {k: {"result": result} for k in ITEMS}


def _site_of(email):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).first().site_id
    finally:
        db.close()


def test_the_checklist_follows_the_fortnightly_form(client, auth):
    r = client.get("/fire-inspections/checklist", headers=auth["mgr"])
    assert r.status_code == 200
    sections = [s["section"] for s in r.json()["sections"]]
    assert sections == ["Fire extinguishers", "Sand buckets", "Fire hose reels"]
    groups = [g["group"] for g in r.json()["sections"][0]["groups"]]
    assert "Pressure indicator" in groups and "Support bracket" in groups


def test_a_site_sends_its_fortnightly_checklist(client, auth):
    today = date.today()
    base = {"kind": "fortnightly", "inspection_date": today.isoformat(), "inspector_name": "Tendai Moyo"}
    # every item must be answered
    partial = {k: v for k, v in list(_all_answers().items())[:5]}
    r = client.post("/fire-inspections/", data={**base, "answers": json.dumps(partial)}, headers=auth["mgr"])
    assert r.status_code == 422 and "Answer every item" in r.json()["detail"]

    answers = _all_answers()
    answers["fe_pointer"] = {"result": "NC", "comment": "Pointer in the red on the forecourt unit"}
    answers["hr_pressure"] = {"result": "NA"}
    r = client.post("/fire-inspections/", data={**base, "answers": json.dumps(answers), "site_id": "2"},
                    headers=auth["mgr"])
    assert r.status_code == 201, r.text
    out = r.json()
    # a site manager always sends for their own site, whatever site_id says
    assert out["site_id"] == _site_of("mgr@x.com")
    assert out["next_due"] == (today + timedelta(days=14)).isoformat()
    assert out["not_conforming"] == 1 and out["answers"]["fe_pointer"]["comment"].startswith("Pointer")

    db = SessionLocal()
    try:
        told = db.query(Notification).filter(Notification.resource == "fire_inspections",
                                             Notification.resource_id == out["id"]).all()
        assert told and "1 item not conforming" in told[0].title
    finally:
        db.close()

    listing = client.get("/fire-inspections/", headers=auth["she"]).json()
    row = next(s for s in listing["schedule"] if s["site_id"] == out["site_id"])
    assert row["fortnightly"]["next_due"] == out["next_due"]
    # other roles can't send them; the date can't be in the future
    assert client.post("/fire-inspections/", data={**base, "answers": json.dumps(answers)},
                       headers=auth["she"]).status_code == 422  # SHE must choose the site
    future = {**base, "inspection_date": (today + timedelta(days=1)).isoformat(), "answers": json.dumps(answers)}
    assert client.post("/fire-inspections/", data=future, headers=auth["mgr"]).status_code == 422


def test_service_and_refill_needs_proof_and_is_due_again_in_six_months(client, auth):
    first = date.today() - timedelta(days=180)
    base = {"kind": "service_refill", "inspection_date": first.isoformat(), "inspector_name": "Tendai Moyo",
            "contractor": "Fire Masters (Pvt) Ltd", "extinguishers": "6",
            "comments": "<p>All <b>refilled</b></p><ul><li>Tags replaced</li></ul><script>alert(1)</script>"}
    r = client.post("/fire-inspections/", data=base, headers=auth["mgr"])
    assert r.status_code == 422 and "proof" in r.json()["detail"]
    r = client.post("/fire-inspections/", data=base, headers=auth["mgr"],
                    files=[("files", ("certificate.pdf", PDF, "application/pdf"))])
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["next_due"] == add_months(first, 6).isoformat()
    assert out["contractor"] == "Fire Masters (Pvt) Ltd" and out["extinguishers"] == 6
    assert len(out["files"]) == 1
    assert "<b>refilled</b>" in out["comments"] and "<li>Tags replaced</li>" in out["comments"]
    assert "script" not in out["comments"]
    f = client.get(f"/fire-inspections/files/{out['files'][0]['id']}", headers=auth["she"])
    assert f.status_code == 200 and f.content == PDF

    # two weeks before the next date, the SHE team (and the site) hear about it once
    db = SessionLocal()
    try:
        due = date.fromisoformat(out["next_due"])
        assert send_reminders(db, today=due - timedelta(days=15)) == 0
        assert send_reminders(db, today=due - timedelta(days=14)) >= 1
        assert send_reminders(db, today=due - timedelta(days=13)) == 0
        she = db.query(User).filter(User.email == "she@x.com").first()
        told = db.query(Notification).filter(Notification.user_id == she.id,
                                             Notification.kind == "fire_service_due").all()
        assert any("due in 14 days" in n.title for n in told)
        # the reminder is marked as sent on the record
        assert db.query(FireInspection).filter(FireInspection.id == out["id"]).first().reminded_at is not None
    finally:
        db.close()


def test_audit_reports_are_kept_apart_from_she_inspections(client, auth):
    r = client.post("/site-inspections/", json={
        "site_id": 1, "inspection_date": date.today().isoformat(), "kind": "audit",
        "audit_body": "  Bureau   Veritas audit team ", "inspectors": "J. Ncube"}, headers=auth["she"])
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "audit" and r.json()["audit_body"] == "Bureau Veritas audit team"
    audits = client.get("/site-inspections/", params={"kind": "audit"}, headers=auth["she"]).json()["inspections"]
    assert audits and all(i["kind"] == "audit" for i in audits)
    she_only = client.get("/site-inspections/", params={"kind": "she"}, headers=auth["she"]).json()["inspections"]
    assert all(i["kind"] == "she" for i in she_only)
