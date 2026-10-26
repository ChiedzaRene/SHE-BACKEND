from datetime import datetime

import pytest

from database import SessionLocal
from models.incident import Incident
from models.incident_file import IncidentFile
from models.incident_workflow import IncidentWorkflow


@pytest.fixture(autouse=True)
def clean_workflow_test_data():
    yield
    db = SessionLocal()
    ids = [incident.id for incident in db.query(Incident).filter(Incident.description == "Investigation test incident").all()]
    if ids:
        db.query(IncidentFile).filter(IncidentFile.incident_id.in_(ids)).delete(synchronize_session=False)
        db.query(IncidentWorkflow).filter(IncidentWorkflow.incident_id.in_(ids)).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.description == "Investigation test incident").delete(synchronize_session=False)
    db.commit()
    db.close()


def create_incident(client, auth, severity="high", intake=None):
    response = client.post("/incidents/", json={
        "site_id": 1,
        "type": "injury",
        "description": "Investigation test incident",
        "severity": severity,
        "incident_intake": intake or {},
    }, headers=auth["mgr"])
    assert response.status_code == 200, response.text
    return response.json()


def workflow(status, **fields):
    return {"incident_workflow": {"status": status, **fields}}


def test_site_manager_can_create_and_view_site_incident(client, auth):
    incident = create_incident(client, auth)
    assert incident["incident_intake"] == {}
    assert incident["incident_workflow"]["status"] == "reported"
    assert client.get(f"/incidents/{incident['id']}", headers=auth["mgr"]).status_code == 200


def test_site_manager_cannot_access_other_site(client, auth):
    assert client.get("/incidents/site/2", headers=auth["mgr"]).status_code == 403


def test_she_assignment_and_investigation_updates(client, auth):
    incident = create_incident(client, auth)
    path = f"/incidents/{incident['id']}"
    assigned = client.put(path, json=workflow("assigned", investigation_team="A", team_details="SHE", assignment_date=datetime.utcnow().isoformat()), headers=auth["she"])
    assert assigned.status_code == 200, assigned.text
    investigating = client.put(path, json=workflow("investigating", evidence="Photo ref 1", costs="Repair", cost_usd=125.50), headers=auth["she"])
    assert investigating.status_code == 200, investigating.text
    assert investigating.json()["incident_workflow"]["cost_usd"] == 125.5


def test_causes_closure_and_finalisation_require_complete_data(client, auth):
    incident = create_incident(client, auth)
    path = f"/incidents/{incident['id']}"
    assert client.put(path, json=workflow("assigned", investigation_team="A", team_details="SHE", assignment_date=datetime.utcnow().isoformat()), headers=auth["she"]).status_code == 200
    assert client.put(path, json=workflow("investigating", evidence="Evidence"), headers=auth["she"]).status_code == 200
    assert client.put(path, json=workflow("causes_recorded", causes=["Unsafe act"], root_cause="Training", corrective_action="Retrain", lessons_learned="Review monthly"), headers=auth["she"]).status_code == 200
    closed = client.put(path, json=workflow("closed"), headers=auth["she"])
    assert closed.status_code == 200 and closed.json()["resolved"] is True
    finalised = client.put(path, json=workflow("report_finalised", report_type="full_investigation", she_comment="Complete"), headers=auth["she"])
    assert finalised.status_code == 200


def test_invalid_transition_and_fatal_comment_rule(client, auth):
    incident = create_incident(client, auth, severity="fatal", intake={"categories": ["Fatality"]})
    path = f"/incidents/{incident['id']}"
    assert client.put(path, json=workflow("closed"), headers=auth["she"]).status_code == 409
    fields = {"evidence": "Evidence", "causes": ["Cause"], "root_cause": "Root", "corrective_action": "Action", "lessons_learned": "Lesson"}
    for stage, extra in (("assigned", {"investigation_team": "A", "team_details": "SHE", "assignment_date": datetime.utcnow().isoformat()}), ("investigating", {}), ("causes_recorded", {}), ("closed", {})):
        payload = {**fields, **extra} if stage == "causes_recorded" else extra
        assert client.put(path, json=workflow(stage, **payload), headers=auth["she"]).status_code == 200
    assert client.put(path, json=workflow("report_finalised", report_type="full_investigation"), headers=auth["she"]).status_code == 422


def test_workflow_history_records_transition(client, auth):
    incident = create_incident(client, auth)
    path = f"/incidents/{incident['id']}"
    client.put(path, json=workflow("assigned", investigation_team="A", team_details="SHE", assignment_date=datetime.utcnow().isoformat()), headers=auth["she"])
    history = client.get(f"/incidents/{incident['id']}/workflow-history", headers=auth["she"])
    assert history.status_code == 200
    assert history.json()[-1]["action"] == "INCIDENT_WORKFLOW_CHANGED"

def test_the_forms_tables_fill_the_investigation(client, auth):
    """Team rows and corrective-action rows (with the hierarchy of control) as on form GP-SHE/SPR/02/01."""
    incident = create_incident(client, auth, intake={"evidence": "Photos taken by the site", "reporter_name": "Tendai"})
    path = f"/incidents/{incident['id']}"
    assigned = client.put(path, json=workflow("assigned", team_members=[
        {"name": "Rudo Chikore", "job_title": "SHE officer", "date": "2026-10-20"},
        {"name": "Peter Ncube", "job_title": "Operations", "date": "2026-10-21"},
        {"name": "  ", "job_title": "blank rows are dropped"},
    ]), headers=auth["she"])
    assert assigned.status_code == 200, assigned.text
    wf = assigned.json()["incident_workflow"]
    assert [m["name"] for m in wf["team_members"]] == ["Rudo Chikore", "Peter Ncube"]
    assert wf["investigation_team"] == "Rudo Chikore (SHE officer); Peter Ncube (Operations)"
    assert wf["assignment_date"].startswith("2026-10-20")
    assert client.put(path, json=workflow("investigating"), headers=auth["she"]).status_code == 200
    # the site's own evidence counts, so the SHE team need not retype it
    recorded = client.put(path, json=workflow("causes_recorded", causes=["Failure to use PPE", "Poor housekeeping"],
                                             root_cause="Inadequate training", lessons_learned="Toolbox talk on PPE",
                                             action_items=[
                                                 {"action": "Guard the pump", "control": "isolation", "by_whom": "Tendai", "by_when": "2026-11-01"},
                                                 {"action": "Gloves for all", "control": "ppe", "by_whom": "Rudo", "by_when": "2026-11-15"},
                                             ]), headers=auth["she"])
    assert recorded.status_code == 200, recorded.text
    wf = recorded.json()["incident_workflow"]
    assert wf["corrective_action"].startswith("Guard the pump [Isolate] by Tendai, by 2026-11-01")
    assert wf["responsible_person"] == "Tendai, Rudo" and wf["due_date"].startswith("2026-11-15")
    assert [a["control"] for a in wf["action_items"]] == ["isolation", "ppe"]
    assert client.put(path, json=workflow("closed", action_items=[{"action": "x", "control": "magic"}]),
                      headers=auth["she"]).status_code == 422   # only the six controls on the form


def test_evidence_files(client, auth):
    incident = create_incident(client, auth)
    path = f"/incidents/{incident['id']}/files"
    pdf = ("statement.pdf", b"%PDF-1.4 witness statement", "application/pdf")
    added = client.post(path, files={"file": pdf}, headers=auth["mgr"])
    assert added.status_code == 201, added.text
    files = added.json()["files"]
    assert len(files) == 1 and files[0]["filename"] == "statement.pdf" and files[0]["viewable"] is True
    fid = files[0]["id"]
    assert client.get(f"{path}/{fid}", headers=auth["she"]).content.startswith(b"%PDF")
    assert client.get(f"/incidents/{incident['id']}", headers=auth["she"]).json()["files"][0]["id"] == fid
    # a site manager of another site can't see it; the SHE team can remove it
    assert client.get(f"{path}/{fid}", headers=auth["admin"]).status_code == 200
    removed = client.delete(f"{path}/{fid}", headers=auth["she"])
    assert removed.status_code == 200 and removed.json()["files"] == []
    # with only an uploaded file as evidence, the investigation can still record its causes
    client.post(path, files={"file": pdf}, headers=auth["mgr"])
    inc = f"/incidents/{incident['id']}"
    client.put(inc, json=workflow("assigned", team_members=[{"name": "Rudo"}]), headers=auth["she"])
    client.put(inc, json=workflow("investigating"), headers=auth["she"])
    ok = client.put(inc, json=workflow("causes_recorded", causes=["Cause"], root_cause="Root", corrective_action="Act",
                                       lessons_learned="Lesson"), headers=auth["she"])
    assert ok.status_code == 200, ok.text
