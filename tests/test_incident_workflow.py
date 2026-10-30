"""The incident investigation, in the order of Glow's form GP-SHE/SPR/02/01:
the site reports it, SHE assign a team (people with accounts), the team logs the causes,
SHE assign corrective actions (with the hierarchy of control) and close it."""
import pytest

from database import SessionLocal, engine
from models.corrective_action import CorrectiveAction
from models.corrective_action_file import CorrectiveActionFile
from models.incident import Incident
from models.incident_file import IncidentFile
from models.incident_workflow import IncidentWorkflow
from models.notification import Notification
from models.user import User
from services.auth_services import hash_password
from services.migrations import ensure_new_columns
from tests.conftest import PASSWORD

DESCRIPTION = "Investigation test incident"
# people who only exist for these tests: a SHE officer, the manager of the other site, operations, a director
PEOPLE = [
    (51, "inv-officer@x.com", "she_officer", None, "Rudo Officer"),
    (52, "inv-mgr2@x.com", "site_manager", 2, "Peter Two"),
    (53, "inv-ops@x.com", "operations", None, "Olivia Ops"),
    (54, "inv-director@x.com", "director", None, "Dan Director"),
]


@pytest.fixture(scope="module")
def people(client):
    db = SessionLocal()
    db.add_all([User(id=uid, email=email, password=hash_password(PASSWORD), role=role, site_id=site, full_name=name)
                for uid, email, role, site, name in PEOPLE])
    db.commit()
    db.close()
    headers = {}
    for uid, email, *_ in PEOPLE:
        r = client.post("/auth/login", data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        headers[email.split("@")[0].removeprefix("inv-")] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    yield headers
    db = SessionLocal()
    ids = [uid for uid, *_ in PEOPLE]
    db.query(Notification).filter(Notification.user_id.in_(ids)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    db.close()


@pytest.fixture(autouse=True)
def clean_workflow_test_data():
    yield
    db = SessionLocal()
    ids = [i.id for i in db.query(Incident).filter(Incident.description == DESCRIPTION).all()]
    if ids:
        ca_ids = [a.id for a in db.query(CorrectiveAction).filter(CorrectiveAction.incident_id.in_(ids)).all()]
        db.query(CorrectiveActionFile).filter(CorrectiveActionFile.action_id.in_(ca_ids or [0])).delete(synchronize_session=False)
        db.query(CorrectiveAction).filter(CorrectiveAction.incident_id.in_(ids)).delete(synchronize_session=False)
        db.query(IncidentFile).filter(IncidentFile.incident_id.in_(ids)).delete(synchronize_session=False)
        db.query(IncidentWorkflow).filter(IncidentWorkflow.incident_id.in_(ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.resource == "incidents", Notification.resource_id.in_(ids)) \
            .delete(synchronize_session=False)
    db.query(Incident).filter(Incident.description == DESCRIPTION).delete(synchronize_session=False)
    db.commit()
    db.close()


def create_incident(client, auth, severity="high", intake=None):
    response = client.post("/incidents/", json={
        "site_id": 1, "type": "injury", "description": DESCRIPTION, "severity": severity,
        "incident_intake": {"evidence": "Photos taken by the site", "site_causes": ["Delivery not watched"]}
        if intake is None else intake,
    }, headers=auth["mgr"])
    assert response.status_code == 200, response.text
    return response.json()


def workflow(status=None, **fields):
    return {"incident_workflow": ({"status": status} if status else {}) | fields}


def assign_ca(client, headers, incident, **over):
    return client.post("/corrective-actions/", json={
        "incident_id": incident["id"], "action_taken": "Fit an overfill alarm on pump 3", "assigned_to": "Manager",
        "control": "redesign", "due_date": "2026-11-15T00:00:00", "priority": "high", **over}, headers=headers)


def close_ca(client, auth, ca_id):
    pdf = ("done.pdf", b"%PDF-1.4 work done", "application/pdf")
    assert client.post(f"/corrective-actions/{ca_id}/files", files={"file": pdf}, headers=auth["mgr"]).status_code == 201
    done = client.post(f"/corrective-actions/{ca_id}/resolve", json={"is_successful": "yes", "resolution_notes": "Done"},
                       headers=auth["she"])
    assert done.status_code == 200, done.text


def to_actions_assigned(client, auth, people, incident):
    """Through the form's steps up to the corrective actions; returns the action's id."""
    path = f"/incidents/{incident['id']}"
    assert client.put(path, json=workflow("assigned", team_members=[{"user_id": 51}]), headers=auth["she"]).status_code == 200
    assert client.put(path, json=workflow("investigating"), headers=people["officer"]).status_code == 200
    assert client.put(path, json=workflow("findings_recorded", evidence="Statements"), headers=people["officer"]).status_code == 200
    assert client.put(path, json=workflow("root_cause_recorded", root_cause="Inadequate training"),
                      headers=auth["she"]).status_code == 200
    ca = assign_ca(client, auth["she"], incident)
    assert ca.status_code == 200
    assert client.put(path, json=workflow("actions_assigned"), headers=auth["she"]).status_code == 200
    return ca.json()["id"]


def test_site_manager_can_create_and_view_site_incident(client, auth):
    incident = create_incident(client, auth, intake={})
    assert incident["incident_intake"] == {}
    assert incident["incident_workflow"]["status"] == "reported"
    assert client.get(f"/incidents/{incident['id']}", headers=auth["mgr"]).status_code == 200


def test_site_manager_cannot_access_other_site(client, auth):
    assert client.get("/incidents/site/2", headers=auth["mgr"]).status_code == 403


def test_the_investigation_follows_the_form(client, auth, people):
    incident = create_incident(client, auth)
    path = f"/incidents/{incident['id']}"

    # SHE pick the team from the people with accounts; names and job titles come from the accounts
    assert client.put(path, json=workflow("assigned"), headers=auth["she"]).status_code == 422
    assigned = client.put(path, json=workflow("assigned", team_members=[
        {"user_id": 51, "date": "2026-10-20"}, {"user_id": 52, "job_title": "Depot manager", "date": "2026-10-21"},
        {"user_id": None}, {"user_id": 51}]), headers=auth["she"])
    assert assigned.status_code == 200, assigned.text
    wf = assigned.json()["incident_workflow"]
    assert wf["team_members"] == [
        {"user_id": 51, "name": "Rudo Officer", "job_title": "SHE Officer", "date": "2026-10-20"},
        {"user_id": 52, "name": "Peter Two", "job_title": "Depot manager", "date": "2026-10-21"}]
    assert wf["investigation_team"] == "Rudo Officer (SHE Officer); Peter Two (Depot manager)"
    assert wf["assignment_date"].startswith("2026-10-20")
    told = client.get("/notifications/", headers=people["mgr2"]).json()
    assert any(f"INC-{incident['id']}" in n["title"] for n in (told["items"] if isinstance(told, dict) else told))

    # the manager of another site is on the team: they now see this incident, and only work on the investigation
    assert incident["id"] in [i["id"] for i in client.get("/incidents/", headers=people["mgr2"]).json()]
    assert client.get(path, headers=people["mgr2"]).status_code == 200
    assert client.put(path, json={"action_plan": "x"}, headers=people["mgr2"]).status_code == 403
    # findings: not before the investigation starts, and only by the team
    assert client.put(path, json=workflow(evidence="too early"), headers=people["mgr2"]).status_code == 409
    assert client.put(path, json=workflow(root_cause="too early"), headers=auth["she"]).status_code == 409
    assert client.put(path, json=workflow("investigating"), headers=people["mgr2"]).status_code == 200
    assert client.put(path, json=workflow(evidence="SHE, not on the team"), headers=auth["she"]).status_code == 403
    # the team logs its findings; the causes, the root cause and the rest are for SHE
    assert client.put(path, json=workflow(lessons_learned="x"), headers=people["mgr2"]).status_code == 403
    assert client.put(path, json=workflow(root_cause="x"), headers=people["mgr2"]).status_code == 403
    assert client.put(path, json=workflow("findings_recorded"), headers=people["mgr2"]).status_code == 422
    found = client.put(path, json=workflow("findings_recorded", evidence="Two statements; the hose was left unattended"),
                       headers=people["mgr2"])
    assert found.status_code == 200, found.text
    assert client.put(path, json=workflow("root_cause_recorded", root_cause="x"), headers=people["mgr2"]).status_code == 403
    # findings are fixed once sent
    assert client.put(path, json=workflow(evidence="changed"), headers=people["mgr2"]).status_code == 409
    # SHE record the root cause; the causes stay the site's
    assert client.put(path, json=workflow(causes=["Something else"]), headers=auth["she"]).status_code == 403
    assert client.put(path, json=workflow("root_cause_recorded"), headers=auth["she"]).status_code == 422
    rooted = client.put(path, json=workflow("root_cause_recorded", root_cause="Inadequate training"), headers=auth["she"])
    assert rooted.status_code == 200, rooted.text
    assert rooted.json()["incident_workflow"]["causes"] == ["Delivery not watched"]
    # the site can no longer change its report now SHE have it
    assert client.put(path, json={"incident_intake": {"location": "x"}}, headers=auth["mgr"]).status_code == 409

    # SHE assign the corrective actions, each with its hierarchy of control
    assert client.put(path, json=workflow("actions_assigned"), headers=auth["she"]).status_code == 422
    assert assign_ca(client, auth["mgr"], incident).status_code == 403
    assert assign_ca(client, auth["she"], incident, control="magic").status_code == 422
    ca = assign_ca(client, auth["she"], incident, site_id=2)
    assert ca.status_code == 200, ca.text
    ca = ca.json()
    assert ca["control"] == "redesign" and ca["site_id"] == 1            # always the incident's site
    assert ca["incident_description"] == DESCRIPTION                     # fixed; the action holds the plan
    moved = client.put(path, json=workflow("actions_assigned"), headers=auth["she"])
    assert moved.status_code == 200, moved.text
    assert moved.json()["incident_workflow"]["corrective_action"] == "Fit an overfill alarm on pump 3"
    assert client.put(path, json=workflow("closed"), headers=people["mgr2"]).status_code == 403

    # the investigation closes only after its corrective actions are closed
    complete = dict(lessons_learned="Watch every delivery", report_type="full_investigation", she_comment="Done")
    waiting = client.put(path, json=workflow("closed", **complete), headers=people["officer"])
    assert waiting.status_code == 422 and waiting.json()["detail"] == "Close the corrective actions first (1 still open)"
    close_ca(client, auth, ca["id"])
    # the Operations Manager may add a comment on any incident (it is required on fatal ones)
    assert client.put(path, json=workflow(operations_manager_comment="Noted"), headers=people["ops"]).status_code == 200

    # closing needs the lessons learnt, the report type and the SHE Officer's comment
    refused = client.put(path, json=workflow("closed", lessons_learned="Watch every delivery"), headers=people["officer"])
    assert refused.status_code == 422
    assert refused.json()["detail"] == "Before closing, record a report type, the SHE Officer's comment"
    closed = client.put(path, json=workflow("closed", lessons_learned="Watch every delivery", report_type="full_investigation",
                                           report_dates={"preliminary_investigation": "2026-10-21", "full_investigation": "2026-10-30"},
                                           report_revised=True, she_comment="Done"), headers=people["officer"])
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["resolved"] is True
    wf = body["incident_workflow"]
    assert wf["status"] == "closed" and wf["report_revised"] is True and wf["closed_at"]
    assert wf["report_dates"] == {"preliminary_investigation": "2026-10-21", "full_investigation": "2026-10-30"}
    history = client.get(f"{path}/workflow-history", headers=auth["she"]).json()
    assert [h["action"] for h in history].count("INCIDENT_WORKFLOW_CHANGED") >= 5


def test_stages_go_in_order_and_a_fatality_needs_the_operations_comment(client, auth, people):
    incident = create_incident(client, auth, severity="fatal", intake={"categories": ["fatality"], "evidence": "Photos"})
    path = f"/incidents/{incident['id']}"
    assert client.put(path, json=workflow("closed"), headers=auth["she"]).status_code == 409
    close_ca(client, auth, to_actions_assigned(client, auth, people, incident))
    closing = dict(lessons_learned="L", report_type="full_investigation", she_comment="S")
    refused = client.put(path, json=workflow("closed", **closing), headers=auth["she"])
    assert refused.status_code == 422 and "Operations Manager" in refused.json()["detail"]
    # operations add their comment, and change nothing else
    assert client.put(path, json=workflow(operations_manager_comment="Reviewed", lessons_learned="x"),
                      headers=people["ops"]).status_code == 403
    assert client.put(path, json=workflow(operations_manager_comment="Reviewed with the board"),
                      headers=people["ops"]).status_code == 200
    assert client.put(path, json=workflow("closed", **closing), headers=auth["she"]).status_code == 200


def test_only_people_who_can_investigate_join_a_team(client, auth, people):
    listed = client.get("/incidents/investigators", headers=people["officer"])
    assert listed.status_code == 200
    roles = {p["id"]: p["role"] for p in listed.json()}
    assert roles[51] == "she_officer" and roles[52] == "site_manager"
    assert 53 not in roles and 54 not in roles            # operations and directors only read
    assert client.get("/incidents/investigators", headers=auth["mgr"]).status_code == 403
    incident = create_incident(client, auth)
    path = f"/incidents/{incident['id']}"
    assert client.put(path, json=workflow("assigned", team_members=[{"user_id": 54}]), headers=auth["she"]).status_code == 422
    assert client.put(path, json=workflow("assigned", team_members=[{"user_id": 999}]), headers=auth["she"]).status_code == 422
    # someone not on the team gets nowhere
    assert client.get(path, headers=people["mgr2"]).status_code == 403
    assert client.put(path, json=workflow("assigned", team_members=[{"user_id": 51}]), headers=auth["mgr"]).status_code == 403


def test_evidence_files(client, auth, people):
    incident = create_incident(client, auth, intake={})
    path = f"/incidents/{incident['id']}/files"
    pdf = ("statement.pdf", b"%PDF-1.4 witness statement", "application/pdf")
    added = client.post(path, files={"file": pdf}, headers=auth["mgr"])
    assert added.status_code == 201, added.text
    files = added.json()["files"]
    assert len(files) == 1 and files[0]["filename"] == "statement.pdf" and files[0]["viewable"] is True
    fid = files[0]["id"]
    assert files[0]["uploaded_by"] is not None   # the app offers removal to the uploader
    assert client.get(f"{path}/{fid}", headers=auth["she"]).content.startswith(b"%PDF")
    assert client.get(f"{path}/{fid}", headers=people["mgr2"]).status_code == 403   # another site's manager
    removed = client.delete(f"{path}/{fid}", headers=auth["she"])
    assert removed.status_code == 200 and removed.json()["files"] == []
    # once on the team, the other site's manager can add evidence, and an uploaded file is evidence enough
    inc = f"/incidents/{incident['id']}"
    client.put(inc, json=workflow("assigned", team_members=[{"user_id": 52}]), headers=auth["she"])
    assert client.post(path, files={"file": pdf}, headers=people["mgr2"]).status_code == 201
    client.put(inc, json=workflow("investigating"), headers=people["mgr2"])
    ok = client.put(inc, json=workflow("findings_recorded", evidence="See the attached file"), headers=people["mgr2"])
    assert ok.status_code == 200, ok.text


def test_older_stages_are_moved_to_the_new_ones(client, auth):
    incident = create_incident(client, auth)
    db = SessionLocal()
    other = create_incident(client, auth)
    db.add(IncidentWorkflow(incident_id=incident["id"], status="report_finalised"))
    db.add(IncidentWorkflow(incident_id=other["id"], status="causes_recorded"))
    db.commit()
    db.close()
    notes = ensure_new_columns(engine)
    assert any("now closed" in note for note in notes) and any("root cause recorded" in note for note in notes)
    status = lambda i: client.get(f"/incidents/{i['id']}", headers=auth["she"]).json()["incident_workflow"]["status"]  # noqa: E731
    assert status(incident) == "closed" and status(other) == "root_cause_recorded"


def test_she_officer_accounts(client, auth, people):
    made = client.post("/users/", json={"email": "inv-officer2@x.com", "password": "Officer-pass-123", "role": "she_officer",
                                        "full_name": "Second Officer"}, headers=auth["admin"])
    assert made.status_code == 200, made.text
    assert made.json()["role"] == "she_officer"
    db = SessionLocal()
    db.query(User).filter(User.email == "inv-officer2@x.com").delete()
    db.commit()
    db.close()
    # a SHE officer does what the SHE team does, such as sharing SHE files and recording trainings
    assert client.get("/she-files/", headers=people["officer"]).status_code == 200


def test_the_description_and_findings_keep_their_formatting_and_the_site_has_no_action_plan(client, auth, people):
    rich = "<p><b>Slipped</b> near pump 3 &amp; hurt wrist</p><script>alert(1)</script><ul><li>first aid</li></ul>"
    incident = create_incident(client, auth)
    path = f"/incidents/{incident['id']}"
    made = client.post("/incidents/", json={"site_id": 1, "type": "injury", "severity": "low", "description": rich,
                                            "incident_intake": {}}, headers=auth["mgr"])
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["description"] == "Slipped near pump 3 & hurt wrist alert(1) first aid"  # plain words; tags gone
    assert body["description_html"] == "<p><b>Slipped</b> near pump 3 &amp; hurt wrist</p>alert(1)<ul><li>first aid</li></ul>"
    db = SessionLocal()
    db.query(Incident).filter(Incident.id == body["id"]).update({"description": DESCRIPTION})  # cleaned up with the rest
    db.commit()
    db.close()
    # too short counts the words, not the formatting
    short = client.post("/incidents/", json={"site_id": 1, "type": "injury", "severity": "low", "description": "<b>Fell</b>"},
                        headers=auth["mgr"])
    assert short.status_code == 422
    # the action plan is not the site's
    assert client.post("/incidents/", json={"site_id": 1, "type": "injury", "severity": "low", "description": DESCRIPTION,
                                            "action_plan": "Fix it"}, headers=auth["mgr"]).status_code == 403
    assert client.put(path, json={"action_plan": "Fix it"}, headers=auth["mgr"]).status_code == 403
    assert client.put(path, json={"action_plan": "Fix it"}, headers=auth["she"]).status_code == 200
    # the findings are formatted too
    client.put(path, json=workflow("assigned", team_members=[{"user_id": 51}]), headers=auth["she"])
    client.put(path, json=workflow("investigating"), headers=people["officer"])
    found = client.put(path, json=workflow(evidence="<p><i>Hose</i> left in the tank</p><img src=x onerror=1>"),
                       headers=people["officer"])
    assert found.json()["incident_workflow"]["evidence"] == "<p><i>Hose</i> left in the tank</p>"


def test_a_corrective_action_closes_only_with_evidence(client, auth, people):
    incident = create_incident(client, auth)
    ca = assign_ca(client, auth["she"], incident).json()
    assert ca["source"] == "incident" and ca["incident_id"] == incident["id"] and ca["files"] == []
    path = f"/corrective-actions/{ca['id']}"
    refused = client.post(f"{path}/resolve", json={"is_successful": "yes", "resolution_notes": "Done"}, headers=auth["mgr"])
    assert refused.status_code == 422 and "evidence" in refused.json()["detail"]
    # reviewed but not effective needs no evidence
    assert client.post(f"{path}/resolve", json={"is_successful": "no", "resolution_notes": "Not yet"},
                       headers=auth["mgr"]).status_code == 200
    photo = ("alarm.png", b"\x89PNG\r\n\x1a\nfake", "image/png")
    added = client.post(f"{path}/files", files={"file": photo}, headers=auth["mgr"])
    assert added.status_code == 201, added.text
    f = added.json()["files"][0]
    assert f["filename"] == "alarm.png" and f["viewable"] is True
    assert client.get(f"{path}/files/{f['id']}", headers=auth["she"]).content.startswith(b"\x89PNG")
    assert client.post(f"{path}/files", files={"file": photo}, headers=people["mgr2"]).status_code == 403   # other site
    closed = client.post(f"{path}/resolve", json={"is_successful": "yes", "resolution_notes": "Fitted"}, headers=auth["mgr"])
    assert closed.status_code == 200 and closed.json()["status"] == "resolved"
    # once closed, its evidence stays as it was
    assert client.delete(f"{path}/files/{f['id']}", headers=auth["she"]).status_code == 409
    assert client.post(f"{path}/files", files={"file": photo}, headers=auth["mgr"]).status_code == 409
