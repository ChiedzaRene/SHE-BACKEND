from datetime import datetime

import pytest

from database import SessionLocal
from models.incident import Incident
from models.incident_workflow import IncidentWorkflow


@pytest.fixture(autouse=True)
def clean_workflow_test_data():
    yield
    db = SessionLocal()
    ids = [incident.id for incident in db.query(Incident).filter(Incident.description == "Investigation test incident").all()]
    if ids:
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