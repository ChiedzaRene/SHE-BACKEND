from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
import json
from datetime import datetime
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, undefer
from database import get_db
from models.incident import Incident
from models.incident_file import IncidentFile
from models.corrective_action import CorrectiveAction
from models.incident_workflow import IncidentWorkflow
from models.site import Site
from models.user import User
from schemas.incident import IncidentCreate, IncidentUpdate, IncidentResponse
from services.access import assert_site_access, assert_site_visible, region_site_ids
from services.pagination import Pagination
from services.auth_services import get_current_user, require_role
from services.audit_service import log_action
from services.files import clean_filename, file_response, is_viewable, read_upload
from services.notifications import notify, short, site_managers, site_name, team, who
from services.safety_metrics import combine, compute_by_site
from typing import List

router = APIRouter(prefix="/incidents", tags=["Incidents"])

PeriodQuery = Query("12m", pattern="^(12m|ytd)$", description="Rolling 12 months or year to date")
WORKFLOW_ROLES = {"super_admin", "admin", "she_team", "she_officer"}
# The order of Glow's Incident Investigation Report Form (GP-SHE/SPR/02/01):
# the site reports it; SHE assign an investigation team; the team investigates and logs the causes;
# SHE assign the corrective actions; SHE close it with the lessons learnt, report type and comments.
WORKFLOW_STAGES = ("reported", "assigned", "investigating", "causes_recorded", "actions_assigned", "closed")
# What a team member who is not in the SHE team may record
TEAM_FIELDS = {"status", "evidence", "witness_reports", "sketches", "causes", "root_cause"}
TEAM_STAGES = {"investigating", "causes_recorded"}
# Who can be put on an investigation team (operations and directors only read)
INVESTIGATOR_ROLES = ("she_officer", "she_team", "admin", "super_admin", "regional_manager", "site_manager")


def _metrics_response(stats: dict, scope: str, period: str) -> dict:
    return {"scope": scope, "period": period, **stats}


def _is_fatal(incident: Incident) -> bool:
    intake = incident.incident_intake or {}
    values = intake.get("categories", intake.get("incident_categories", []))
    if isinstance(values, str):
        values = [values]
    return incident.severity.lower() == "fatal" or any(str(value).lower() == "fatality" for value in values)


def _team_ids(incident: Incident) -> set:
    workflow = incident._workflow
    return {m.get("user_id") for m in ((workflow.team_members if workflow else None) or []) if m.get("user_id")}


def _on_team(incident: Incident, user: User) -> bool:
    return user.id in _team_ids(incident)


def _assert_can_see(db: Session, user: User, incident: Incident) -> None:
    """The incident's site's people see it, and so does everyone on its investigation team."""
    if not _on_team(incident, user):
        assert_site_visible(db, user, incident.site_id)


def _incident_actions(db: Session, incident: Incident) -> list:
    return db.query(CorrectiveAction).filter(CorrectiveAction.incident_id == incident.id).order_by(CorrectiveAction.id).all()


def _validate_workflow(db: Session, incident: Incident, workflow: IncidentWorkflow, changes: dict) -> None:
    next_stage = changes.get("status")
    if next_stage is None or next_stage == workflow.status:
        return
    current = workflow.status if workflow.status in WORKFLOW_STAGES else "reported"
    position = WORKFLOW_STAGES.index(current)
    expected = WORKFLOW_STAGES[position + 1] if position + 1 < len(WORKFLOW_STAGES) else None
    if next_stage != expected:
        raise HTTPException(status_code=409, detail=f"Invalid workflow transition from {workflow.status} to {next_stage}")
    if next_stage == "assigned" and not changes.get("team_members", workflow.team_members):
        raise HTTPException(status_code=422, detail="Choose at least one person for the investigation team")
    if next_stage == "causes_recorded":
        causes = changes.get("causes", workflow.causes)
        # the site's own evidence (reported with the incident) and uploaded files count too
        evidence = (changes.get("evidence", workflow.evidence) or (incident.incident_intake or {}).get("evidence")
                    or incident._files)
        if not (evidence and causes and len(causes) <= 3 and changes.get("root_cause", workflow.root_cause)):
            raise HTTPException(status_code=422, detail="Evidence, one to three causes and the root cause are required")
    if next_stage == "actions_assigned" and not _incident_actions(db, incident):
        raise HTTPException(status_code=422, detail="Assign at least one corrective action first")
    if next_stage == "closed":
        missing = [label for key, label in (("lessons_learned", "lessons learnt"), ("report_type", "a report type"),
                                            ("she_comment", "the SHE Officer's comment"))
                   if not changes.get(key, getattr(workflow, key))]
        if _is_fatal(incident) and not changes.get("operations_manager_comment", workflow.operations_manager_comment):
            missing.append("the Operations Manager's comment (fatal incident)")
        if missing:
            raise HTTPException(status_code=422, detail="Before closing, record " + ", ".join(missing))


def _parse_day(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


ROLE_TITLES = {"she_officer": "SHE Officer", "she_team": "SHE team", "admin": "Admin", "super_admin": "Admin",
               "regional_manager": "Regional manager", "site_manager": "Site manager"}


def _team_from_accounts(db: Session, changes: dict) -> None:
    """Team rows name people with accounts; the summary fields are filled from them."""
    if "team_members" not in changes:
        return
    rows = [m for m in (changes.get("team_members") or []) if m.get("user_id")]
    people = {u.id: u for u in db.query(User).filter(User.id.in_([m["user_id"] for m in rows] or [0]),
                                                     User.is_active.is_(True)).all()}
    members = []
    for m in rows:
        person = people.get(m["user_id"])
        if person is None or person.role not in INVESTIGATOR_ROLES:
            raise HTTPException(status_code=422, detail="Investigation team members must be active people who can investigate")
        if any(x["user_id"] == person.id for x in members):
            continue
        members.append({"user_id": person.id, "name": person.full_name or person.email,
                        "job_title": m.get("job_title") or ROLE_TITLES.get(person.role), "date": m.get("date")})
    changes["team_members"] = members
    if members:
        changes["investigation_team"] = "; ".join(f"{m['name']} ({m['job_title']})" for m in members)
        changes["team_details"] = "; ".join(", ".join(p for p in (m["name"], m["job_title"], m["date"]) if p) for m in members)
        days = [d for d in (_parse_day(m.get("date")) for m in members) if d]
        changes["assignment_date"] = min(days) if days else datetime.utcnow()


def _apply_workflow(incident: Incident, workflow_data, user: User, request: Request, db: Session) -> None:
    changes = workflow_data if isinstance(workflow_data, dict) else workflow_data.model_dump(exclude_unset=True)
    if user.role == "operations":
        if set(changes) != {"operations_manager_comment"} or not _is_fatal(incident):
            raise HTTPException(status_code=403, detail="Operations Managers may only comment on fatal incidents")
    elif user.role not in WORKFLOW_ROLES:
        # the investigation team records what they find: evidence, causes and the root cause
        if not _on_team(incident, user):
            raise HTTPException(status_code=403, detail="Only the SHE team and the investigation team may update the investigation")
        if set(changes) - TEAM_FIELDS or changes.get("status", "investigating") not in TEAM_STAGES:
            raise HTTPException(status_code=403, detail="The investigation team records the evidence and causes; the SHE team does the rest")
    workflow = incident._workflow
    if workflow is None:
        workflow = IncidentWorkflow(incident_id=incident.id)
        db.add(workflow)
        db.flush()
    previous = workflow.status
    before_team = _team_ids(incident)
    _team_from_accounts(db, changes)
    if user.role != "operations":
        _validate_workflow(db, incident, workflow, changes)
    for key, value in changes.items():
        setattr(workflow, key, value)
    if changes.get("status") == "actions_assigned":
        actions = _incident_actions(db, incident)
        workflow.corrective_action = "\n".join(a.action_taken for a in actions)
        workflow.responsible_person = ", ".join(dict.fromkeys(a.assigned_to for a in actions if a.assigned_to))[:255]
        dues = [a.due_date for a in actions if a.due_date]
        workflow.due_date = max(dues) if dues else None
    if changes.get("status") == "closed":
        workflow.closed_at = datetime.utcnow()
        workflow.closed_by_id = user.id
        incident.resolved = True
    db.commit()
    db.refresh(workflow)
    details = json.dumps({"previous_stage": previous, "new_stage": workflow.status,
                          "changed_fields": sorted(changes)})
    log_action(db=db, user=user, action="INCIDENT_WORKFLOW_CHANGED", resource="incidents",
               resource_id=incident.id, details=details, ip_address=request.client.host)
    _tell_people(db, incident, user, previous, workflow, before_team)


def _tell_people(db: Session, incident: Incident, actor: User, previous: str, workflow: IncidentWorkflow,
                 before_team: set) -> None:
    where = site_name(db, incident.site_id)
    now_on = {m.get("user_id") for m in (workflow.team_members or []) if m.get("user_id")}
    added = db.query(User).filter(User.id.in_(now_on - before_team or {0})).all()
    notify(db, added, kind="incident_team",
           title=f"You are on the investigation team for INC-{incident.id} at {where}",
           message=f"{who(actor)} assigned you to investigate: {short(incident.description)}",
           link="/incidents", resource="incidents", resource_id=incident.id, actor=actor)
    if workflow.status != previous and workflow.status in ("causes_recorded", "closed"):
        done = "The causes were recorded" if workflow.status == "causes_recorded" else "The investigation was closed"
        notify(db, team(db) + (site_managers(db, incident.site_id) if workflow.status == "closed" else []),
               kind="incident_stage", title=f"INC-{incident.id} at {where}: {done.lower()}",
               message=f"{done} by {who(actor)}.",
               link="/incidents", resource="incidents", resource_id=incident.id, actor=actor)


@router.get("/investigators")
def list_investigators(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The people the SHE team can put on an investigation team."""
    if current_user.role not in WORKFLOW_ROLES:
        raise HTTPException(status_code=403, detail="Only the SHE team assigns investigation teams")
    people = (db.query(User).filter(User.role.in_(INVESTIGATOR_ROLES), User.is_active.is_(True))
              .order_by(User.full_name, User.email).all())
    return [{"id": u.id, "name": u.full_name or u.email, "role": u.role, "job_title": ROLE_TITLES.get(u.role),
             "site_id": u.site_id} for u in people]


# Get all incidents
@router.get("/", response_model=List[IncidentResponse])
def get_all_incidents(
    response: Response,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Incident)
    seen = None
    if current_user.role == "site_manager":
        seen = Incident.site_id == current_user.site_id
    mine = region_site_ids(db, current_user)
    if mine is not None:  # a regional manager sees the incidents at the sites in their region
        seen = Incident.site_id.in_(mine or [0])
    if seen is not None:
        # and anyone on an investigation team sees that incident wherever it happened
        investigating = [w.incident_id for w in db.query(IncidentWorkflow).filter(IncidentWorkflow.team_members.isnot(None)).all()
                         if current_user.id in {m.get("user_id") for m in (w.team_members or [])}]
        query = query.filter(or_(seen, Incident.id.in_(investigating)) if investigating else seen)
    return page.apply(query, response, Incident.id.desc()).all()

# Totals for the dashboards (how many, how many still open, split by type) without sending every incident
@router.get("/summary")
def get_incident_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = []
    if current_user.role == "site_manager":
        scope.append(Incident.site_id == current_user.site_id)
    by_type = (
        db.query(Incident.type, func.count(Incident.id))
        .filter(*scope)
        .group_by(Incident.type)
        .order_by(func.count(Incident.id).desc())
        .all()
    )
    open_count = db.query(func.count(Incident.id)).filter(*scope, Incident.resolved.isnot(True)).scalar() or 0
    by_site = db.query(Incident.site_id, func.count(Incident.id)).filter(*scope).group_by(Incident.site_id).all()
    return {
        "total": sum(n for _, n in by_type),
        "open": open_count,
        "by_type": [{"name": t or "Other", "value": n} for t, n in by_type],
        # all-time count per site, for the map bubbles
        "by_site": [{"site_id": sid, "value": n} for sid, n in by_site if sid is not None],
    }


# Per-site rates (LTIFR) for the dashboards: one query instead of downloading every incident
@router.get("/metrics/by-site")
def get_metrics_by_site(
    period: str = PeriodQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        site_ids = [current_user.site_id]
    else:
        site_ids = [row[0] for row in db.query(Site.id).all()]
    stats = compute_by_site(db, site_ids, period)
    return [{"site_id": sid, "period": period, **s} for sid, s in sorted(stats.items())]


# Global metrics
@router.get("/metrics/global")
def get_global_metrics(
    period: str = PeriodQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        site_ids = [current_user.site_id]
        scope = f"site_{current_user.site_id}"
    else:
        site_ids = [row[0] for row in db.query(Site.id).all()]
        scope = "global"
    stats = combine(compute_by_site(db, site_ids, period).values())
    return _metrics_response(stats, scope, period)


# Site metrics
@router.get("/metrics/{site_id}")
def get_site_metrics(
    site_id: int,
    period: str = PeriodQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, site_id)
    stats = compute_by_site(db, [site_id], period)[site_id]
    return _metrics_response(stats, f"site_{site_id}", period)

# Get incidents by site
@router.get("/site/{site_id}", response_model=List[IncidentResponse])
def get_site_incidents(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    assert_site_visible(db, current_user, site_id)
    return db.query(Incident).filter(Incident.site_id == site_id).all()

@router.get("/{incident_id}/workflow-history")
def get_workflow_history(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _assert_can_see(db, current_user, incident)
    from models.audit_log import AuditLog
    return db.query(AuditLog).filter(
        AuditLog.resource == "incidents",
        AuditLog.resource_id == incident_id,
        AuditLog.action == "INCIDENT_WORKFLOW_CHANGED",
    ).order_by(AuditLog.timestamp.asc()).all()


# Get one incident
@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _assert_can_see(db, current_user, incident)
    return incident

# Create incident
@router.post("/", response_model=IncidentResponse)
def create_incident(
    request: Request,
    incident_data: IncidentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and incident_data.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Cannot log incidents for another site")
    assert_site_visible(db, current_user, incident_data.site_id)
    new_incident = Incident(
        **incident_data.model_dump(),
        user_id=current_user.id
    )
    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)

    log_action(
        db=db,
        user=current_user,
        action="CREATE_INCIDENT",
        resource="incidents",
        resource_id=new_incident.id,
        details=f"Type: {new_incident.type}, Severity: {new_incident.severity}",
        ip_address=request.client.host
    )
    where = site_name(db, new_incident.site_id)
    hurt = f" ({new_incident.injured_person} hurt)" if new_incident.injured_person else ""
    notify(
        db, team(db) + site_managers(db, new_incident.site_id),
        kind="incident_recorded",
        title=f"New {(new_incident.type or 'incident').replace('-', ' ')} at {where}{hurt}",
        message=f"{who(current_user)} recorded a {new_incident.severity} incident: {short(new_incident.description)}",
        link="/incidents", resource="incidents", resource_id=new_incident.id, actor=current_user,
    )
    return new_incident

# Update incident
@router.put("/{incident_id}", response_model=IncidentResponse)
def update_incident(
    request: Request,
    incident_id: int,
    incident_data: IncidentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _assert_can_see(db, current_user, incident)
    changes = incident_data.model_dump(exclude_unset=True)
    workflow_data = changes.pop("incident_workflow", None)
    intake = changes.pop("incident_intake", None)
    if (intake is not None or changes) and _on_team(incident, current_user):
        try:  # someone from elsewhere on the team works on the investigation only
            assert_site_visible(db, current_user, incident.site_id)
        except HTTPException:
            raise HTTPException(status_code=403, detail="As an investigation team member you may update the investigation only")
    if workflow_data is not None:
        _apply_workflow(incident, workflow_data, current_user, request, db)
    if current_user.role == "operations" and (intake is not None or changes):
        raise HTTPException(status_code=403, detail="Operations Managers may only comment on fatal incidents")
    if intake is not None:
        if current_user.role != "site_manager" and current_user.role not in WORKFLOW_ROLES:
            raise HTTPException(status_code=403, detail="You don't have permission to update incident intake")
        stage = incident._workflow.status if incident._workflow else "reported"
        if current_user.role == "site_manager" and stage != "reported":
            raise HTTPException(status_code=409, detail="The SHE team has taken this report on, so the site can no longer change it")
        incident.incident_intake = {**(incident.incident_intake or {}), **intake}
    if "description" in changes and (changes["description"] or "").strip() != (incident.description or "").strip():
        raise HTTPException(status_code=409, detail="An incident's description can't be changed once it is logged. Add to the action plan instead.")
    changes.pop("description", None)
    if "action_plan" in changes:
        changes["action_plan"] = (changes["action_plan"] or "").strip() or None
    for key, value in changes.items():
        setattr(incident, key, value)
    db.commit()
    db.refresh(incident)
    if changes:
        log_action(db=db, user=current_user, action="UPDATE_INCIDENT", resource="incidents",
                   resource_id=incident.id, details=f"Updated incident #{incident.id}",
                   ip_address=request.client.host)
    return incident



# ---- Evidence files: documents, witness or victim reports, pictures, sketch diagrams ----

EVIDENCE_ROLES = WORKFLOW_ROLES | {"site_manager"}


def _incident_for_files(db: Session, user: User, incident_id: int) -> Incident:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _assert_can_see(db, user, incident)
    return incident


@router.post("/{incident_id}/files", response_model=IncidentResponse, status_code=201)
async def add_evidence(
    request: Request,
    incident_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Attach a piece of evidence. The site does so while reporting; the SHE team at any stage."""
    incident = _incident_for_files(db, current_user, incident_id)
    if current_user.role not in EVIDENCE_ROLES and not _on_team(incident, current_user):
        raise HTTPException(status_code=403, detail="You can't add evidence to this incident.")
    if len(incident._files) >= 20:
        raise HTTPException(status_code=422, detail="An incident can have up to 20 evidence files.")
    filename, content_type = clean_filename(file)
    data = await read_upload(file)
    db.add(IncidentFile(incident_id=incident.id, filename=filename, content_type=content_type, size=len(data),
                        data=data, uploaded_by=current_user.id))
    db.commit()
    db.refresh(incident)
    log_action(db=db, user=current_user, action="UPDATE_INCIDENT", resource="incidents", resource_id=incident.id,
               details=f"Added evidence {filename} to incident #{incident.id}",
               ip_address=request.client.host if request.client else None)
    return incident


@router.get("/{incident_id}/files/{file_id}")
def get_evidence(
    incident_id: int,
    file_id: int,
    download: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _incident_for_files(db, current_user, incident_id)
    f = (db.query(IncidentFile).options(undefer(IncidentFile.data))
         .filter(IncidentFile.id == file_id, IncidentFile.incident_id == incident_id).first())
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    kind = "inline" if is_viewable(f.filename) and not download else "attachment"
    return file_response(f.data, f.content_type, f.filename, kind)


@router.delete("/{incident_id}/files/{file_id}", response_model=IncidentResponse)
def remove_evidence(
    request: Request,
    incident_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _incident_for_files(db, current_user, incident_id)
    f = db.query(IncidentFile).filter(IncidentFile.id == file_id, IncidentFile.incident_id == incident_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if current_user.role not in WORKFLOW_ROLES and f.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Only the person who added this file or the SHE team can remove it.")
    db.delete(f)
    db.commit()
    db.refresh(incident)
    log_action(db=db, user=current_user, action="UPDATE_INCIDENT", resource="incidents", resource_id=incident.id,
               details=f"Removed evidence {f.filename} from incident #{incident.id}",
               ip_address=request.client.host if request.client else None)
    return incident
