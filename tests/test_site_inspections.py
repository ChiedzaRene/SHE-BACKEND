"""Inspection reports: SHE drafts -> submits to the region -> regional acknowledges and assigns ->
site completes -> SHE reviews and closes. NCs are numbered report/site code/sequence."""
from datetime import date, timedelta

import pytest

from database import SessionLocal
from models.corrective_action import CorrectiveAction
from models.notification import Notification
from models.site import Site
from models.user import User
from services.auth_services import hash_password

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture(scope="module")
def people(client, auth):
    db = SessionLocal()
    db.query(Site).filter(Site.id == 1).update({Site.region: "Harare", Site.code: "CBD"})
    db.query(Site).filter(Site.id == 2).update({Site.region: "Bulawayo"})
    for uid, email, region in ((40, "regional@x.com", "Harare"), (41, "byo@x.com", "Bulawayo")):
        if not db.query(User).filter(User.id == uid).first():
            db.add(User(id=uid, email=email, password=hash_password("password123"), role="regional_manager",
                        region=region, full_name=email.split("@")[0].title()))
    db.commit()
    db.close()

    def login(email):
        r = client.post("/auth/login", data={"username": email, "password": "password123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return {**auth, "regional": login("regional@x.com"), "other_region": login("byo@x.com")}


def _draft(client, h, site_id=1):
    r = client.post("/site-inspections/", json={
        "site_id": site_id, "inspection_date": date.today().isoformat(), "inspectors": "Rudo Chikore",
        "introduction": "<p>The SHE Department conducted a <b>comprehensive</b> inspection<script>alert(1)</script></p>",
        "objectives": "<ul><li><i>Detect</i> hazards</li><li><u>Verify</u> readiness</li></ul>",
        "findings_summary": "<p>Overall the site is performing well.</p>",
        "conformities": "<ul><li>Forecourt clean</li></ul>",
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_only_she_writes_reports_and_text_keeps_safe_formatting(client, people):
    assert client.post("/site-inspections/", json={"site_id": 1, "inspection_date": "2026-10-01"},
                       headers=people["mgr"]).status_code == 403
    assert client.post("/site-inspections/", json={"site_id": 1, "inspection_date": "2026-10-01"},
                       headers=people["regional"]).status_code == 403
    r = _draft(client, people["she"])
    assert "<b>comprehensive</b>" in r["introduction"] and "script" not in r["introduction"]
    assert "<i>Detect</i>" in r["objectives"] and "<u>Verify</u>" in r["objectives"]
    assert r["status"] == "draft" and r["site_code"] == "CBD"
    # drafts are not visible to the site or the region yet
    assert client.get(f"/site-inspections/{r['id']}", headers=people["mgr"]).status_code == 404
    assert client.get(f"/site-inspections/{r['id']}", headers=people["regional"]).status_code == 404


def test_full_workflow(client, people):
    she, mgr, reg = people["she"], people["mgr"], people["regional"]
    insp = _draft(client, she)
    iid, number = insp["id"], insp["number"]
    for title in ("Oil separator", "Electrical distribution board", "Faded directional arrows"):
        insp = client.post(f"/site-inspections/{iid}/ncs", json={
            "title": title, "details": "<p>Found <b>nearly full</b></p>", "reference": "ZWS 970:2020 Clause 17(F)"},
            headers=she).json()
    assert [n["serial"] for n in insp["ncs"]] == [f"{number}/CBD/01", f"{number}/CBD/02", f"{number}/CBD/03"]
    # deleting a draft NC renumbers the rest
    insp = client.delete(f"/site-inspections/ncs/{insp['ncs'][1]['id']}", headers=she).json()
    assert [n["serial"] for n in insp["ncs"]] == [f"{number}/CBD/01", f"{number}/CBD/02"]
    nc1, nc2 = insp["ncs"]
    insp = client.post(f"/site-inspections/ncs/{nc1['id']}/photos", files={"file": ("pit.png", PNG, "image/png")},
                       headers=she).json()
    photo = insp["ncs"][0]["photos"][0]
    # proof can be a photo, a PDF or a document; nothing that could run in a browser
    with_pdf = client.post(f"/site-inspections/ncs/{nc1['id']}/photos", files={"file": ("checklist.pdf", b"%PDF-1.4", "application/pdf")},
                           headers=she).json()
    assert [(p["filename"], p["is_image"], p["viewable"]) for p in with_pdf["ncs"][0]["photos"]] == [
        ("pit.png", True, True), ("checklist.pdf", False, True)]
    assert client.post(f"/site-inspections/ncs/{nc1['id']}/photos", files={"file": ("x.html", b"<script>", "text/html")},
                       headers=she).status_code == 400
    # proof of the inspection itself
    rep = client.post(f"/site-inspections/{iid}/attachments",
                      files={"file": ("signed-checklist.docx", b"PK\x03\x04", "application/octet-stream")}, headers=she).json()
    doc = rep["attachments"][0]
    assert doc["kind"] == "report" and doc["viewable"] is False
    assert client.post(f"/site-inspections/{iid}/attachments", files={"file": ("a.pdf", b"%PDF", "application/pdf")},
                       headers=mgr).status_code == 403

    # submit: NCs go to the regional office of the site's region
    sub = client.post(f"/site-inspections/{iid}/submit", headers=she).json()
    assert sub["status"] == "submitted" and {n["status"] for n in sub["ncs"]} == {"raised"}
    assert client.put(f"/site-inspections/{iid}", json={"inspectors": "x"}, headers=she).status_code == 409
    db = SessionLocal()
    assert db.query(Notification).filter(Notification.user_id == 40, Notification.kind == "ncs_raised").count() == 1
    assert db.query(Notification).filter(Notification.user_id == 41, Notification.kind == "ncs_raised").count() == 0
    db.close()
    # the site sees the whole report; another region doesn't
    seen = client.get(f"/site-inspections/{iid}", headers=mgr).json()
    assert seen["introduction"] and seen["ncs"][0]["photos"] and seen["attachments"]
    assert client.get(f"/site-inspections/photos/{photo['id']}", headers=mgr).content == PNG
    word = client.get(f"/site-inspections/photos/{doc['id']}", headers=mgr)
    assert word.status_code == 200 and word.headers["content-disposition"].startswith("attachment")
    assert client.get(f"/site-inspections/photos/{doc['id']}", headers=people["other_region"]).status_code == 404
    assert client.get(f"/site-inspections/{iid}", headers=people["other_region"]).status_code == 404

    # the regional office acknowledges: recommendation, who, deadline -> a corrective action opens
    due = (date.today() + timedelta(days=14)).isoformat()
    people_list = client.get(f"/site-inspections/{iid}/assignees", headers=reg).json()
    assert {"Site manager", "SHE office"} <= {p["label"] for p in people_list}
    assert client.post(f"/site-inspections/ncs/{nc1['id']}/acknowledge",
                       json={"recommendation": "Drain it", "assigned_to": 3, "due_date": due},
                       headers=mgr).status_code == 403
    assert client.post(f"/site-inspections/ncs/{nc1['id']}/acknowledge",
                       json={"recommendation": "Drain it", "assigned_to": 41, "due_date": due},
                       headers=reg).status_code == 422          # not someone who can take it
    ack = client.post(f"/site-inspections/ncs/{nc1['id']}/acknowledge",
                      json={"recommendation": "<p>Drain and clean the <b>oil separator</b></p>", "assigned_to": 3,
                            "due_date": due}, headers=reg)
    assert ack.status_code == 200, ack.text
    n = ack.json()["ncs"][0]
    assert n["status"] == "assigned" and n["assigned_to_name"] == "Manager" and n["due_date"] == due
    assert n["acknowledged_by_name"] == "Regional"
    db = SessionLocal()
    ca = db.query(CorrectiveAction).filter(CorrectiveAction.id == n["corrective_action_id"]).first()
    assert ca.nc_id == nc1["id"] and ca.site_id == 1 and ca.status == "open" and n["serial"] in ca.action_taken
    assert db.query(Notification).filter(Notification.user_id == 3, Notification.kind == "nc_assigned").count() >= 1
    db.close()
    # the action is managed from the inspection, not the corrective actions page
    assert client.post(f"/corrective-actions/{ca.id}/resolve", json={"resolution_notes": "x", "is_successful": "yes"},
                       headers=people["admin"]).status_code == 409
    assert any(a["nc_id"] == nc1["id"] and a["inspection_id"] == iid
               for a in client.get("/corrective-actions/", headers=reg).json())

    # the site completes it and says how; SHE reviews
    assert client.post(f"/site-inspections/ncs/{nc1['id']}/review", json={"outcome": "closed"},
                       headers=she).status_code == 409          # not completed yet
    done = client.post(f"/site-inspections/ncs/{nc1['id']}/complete",
                       data={"notes": "Separator drained by Clean Co on 20 Oct, receipt filed."},
                       files=[("files", ("after.png", PNG, "image/png")), ("files", ("receipt.pdf", b"%PDF-1.4", "application/pdf"))],
                       headers=mgr)
    assert done.status_code == 200, done.text
    n = done.json()["ncs"][0]
    assert n["status"] == "completed" and n["completed_by_name"] == "Manager"
    assert [(p["kind"], p["filename"]) for p in n["photos"]] == [
        ("finding", "pit.png"), ("finding", "checklist.pdf"), ("evidence", "after.png"), ("evidence", "receipt.pdf")]
    # not done properly: back to the site with a reason
    assert client.post(f"/site-inspections/ncs/{nc1['id']}/review", json={"outcome": "open"},
                       headers=she).status_code == 422
    back = client.post(f"/site-inspections/ncs/{nc1['id']}/review",
                       json={"outcome": "open", "comment": "Sludge still visible"}, headers=she).json()["ncs"][0]
    assert back["status"] == "assigned" and back["review_comment"] == "Sludge still visible"
    client.post(f"/site-inspections/ncs/{nc1['id']}/complete", data={"notes": "Cleaned again, photo attached."},
                headers=mgr)
    closed = client.post(f"/site-inspections/ncs/{nc1['id']}/review", json={"outcome": "closed"}, headers=she).json()
    n = closed["ncs"][0]
    assert n["status"] == "closed" and n["reviewed_by_name"] == "she@x.com" and n["reviewed_at"]
    assert closed["status"] == "submitted"                       # NC 2 still open
    db = SessionLocal()
    assert db.query(CorrectiveAction).filter(CorrectiveAction.nc_id == nc1["id"]).one().status == "resolved"
    db.close()

    # a later report at the same site lists the uncleared NC as a previous NC
    later = _draft(client, she)
    assert [p["serial"] for p in later["previous_ncs"]] == [nc2["serial"]]
    assert later["previous_ncs"][0]["from_report"] == number

    # finishing the last NC closes the report
    client.post(f"/site-inspections/ncs/{nc2['id']}/acknowledge",
                json={"recommendation": "Label the board", "assigned_to": 3, "due_date": due}, headers=reg)
    mine = client.get("/site-inspections/my-ncs", headers=mgr).json()
    assert any(m["serial"] == nc2["serial"] for m in mine)
    client.post(f"/site-inspections/ncs/{nc2['id']}/complete", data={"notes": "Board labelled."}, headers=mgr)
    final = client.post(f"/site-inspections/ncs/{nc2['id']}/review", json={"outcome": "closed"}, headers=she).json()
    assert final["status"] == "closed" and final["nc_counts"]["closed"] == 2
    assert client.get(f"/site-inspections/{later['id']}", headers=she).json()["previous_ncs"] == []


def test_submitting_needs_the_introduction_and_summary(client, people):
    r = client.post("/site-inspections/", json={"site_id": 1, "inspection_date": date.today().isoformat()},
                    headers=people["she"]).json()
    assert client.post(f"/site-inspections/{r['id']}/submit", headers=people["she"]).status_code == 422
    assert client.delete(f"/site-inspections/{r['id']}", headers=people["she"]).status_code == 200


def test_list_is_filtered_by_role_and_region(client, people):
    she_list = client.get("/site-inspections/", headers=people["she"]).json()
    assert "Harare" in she_list["regions"]
    assert all(i["status"] != "draft" for i in client.get("/site-inspections/", headers=people["mgr"]).json()["inspections"])
    assert client.get("/site-inspections/", headers=people["other_region"]).json()["inspections"] == []
    harare = client.get("/site-inspections/", params={"region": "Harare"}, headers=people["she"]).json()["inspections"]
    assert harare and all(i["region"] == "Harare" for i in harare)


def test_regional_managers_need_a_known_region(client, people):
    base = {"email": "newreg@x.com", "password": "password123", "role": "regional_manager"}
    assert client.post("/users", json=base, headers=people["admin"]).status_code == 422
    assert client.post("/users", json={**base, "region": "Atlantis"}, headers=people["admin"]).status_code == 422
    ok = client.post("/users", json={**base, "region": "Harare"}, headers=people["admin"])
    assert ok.status_code == 200 and ok.json()["region"] == "Harare"
    # one of the fixed regions works even before any site is in it, and the manager shows against it
    south = client.post("/users", json={**base, "email": "south@x.com", "full_name": "Sipho South", "region": "south east"},
                        headers=people["admin"])
    assert south.status_code == 200 and south.json()["region"] == "South East"
    regions = client.get("/sites/regions", headers=people["admin"]).json()["regions"]
    assert next(r for r in regions if r["name"] == "South East")["managers"] == ["Sipho South"]


def test_site_code_is_saved_upper_case(client, people):
    r = client.post("/sites/", json={"name": "Code Test", "address": "1 Rd", "code": "ctr"}, headers=people["admin"])
    assert r.status_code == 201 and r.json()["code"] == "CTR"
