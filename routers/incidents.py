from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
import json
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session, undefer
from database import get_db
from models.incident import Incident
from models.incident_file import IncidentFile
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
WORKFLOW_ROLES = {"super_admin", "admin", "she_team"}
WORKFLOW_STAGES = ("reported", "assigned", "investigating", "causes_recorded", "closed", "report_finalised")
REPORT_FINALISED = "report_finalised"


def _metrics_response(stats: dict, scope: str, period: str) -> dict:
    return {"scope": scope, "period": period, **stats}


def _is_fatal(incident: Incident) -> bool:
    intake = incident.incident_intake or {}
    values = intake.get("categories", intake.get("incident_categories", []))
    if isinstance(values, str):
        values = [values]
    return incident.severity.lower() == "fatal" or any(str(value).lower() == "fatality" for value in values)


def _validate_workflow(incident: Incident, workflow: IncidentWorkflow, changes: dict) -> None:
    next_stage = changes.get("status")
    if next_stage is None or next_stage == workflow.status:
        return
    expected = WORKFLOW_STAGES[WORKFLOW_STAGES.index(workflow.status) + 1] if workflow.status != REPORT_FINALISED else None
    if next_stage != expected:
        raise HTTPException(status_code=409, detail=f"Invalid workflow transition from {workflow.status} to {next_stage}")
    if next_stage == "assigned" and not all((
        changes.get("investigation_team", workflow.investigation_team),
        changes.get("team_details", workflow.team_details),
        changes.get("assignment_date", workflow.assignment_date),
    )):
        raise HTTPException(status_code=422, detail="Team members, team details and assignment date are required")
    if next_stage in ("causes_recorded", "closed", REPORT_FINALISED):
        causes = changes.get("causes", workflow.causes)
        # the site's own evidence (reported with the incident) and uploaded files count too
        evidence = (changes.get("evidence", workflow.evidence) or (incident.incident_intake or {}).get("evidence")
                    or incident._files)
        required = (
            evidence,
            causes and len(causes) <= 3,
            changes.get("root_cause", workflow.root_cause),
            changes.get("corrective_action", workflow.corrective_action),
            changes.get("lessons_learned", workflow.lessons_learned),
        )
        if not all(required):
            raise HTTPException(status_code=422, detail="Evidence, up to three causes, root cause, corrective action and lessons learnt are required")
    if next_stage == REPORT_FINALISED:
        if not changes.get("report_type", workflow.report_type):
            raise HTTPException(status_code=422, detail="report_type is required before finalisation")
        if _is_fatal(incident) and not changes.get("operations_manager_comment", workflow.operations_manager_comment):
            raise HTTPException(status_code=422, detail="Operations Manager comments are required for fatal incidents")


def _parse_day(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


CONTROL_LABELS = {"elimination": "Elimination", "substitution": "Substitution", "isolation": "Isolate",
                  "redesign": "Redesign", "administration": "Administration", "ppe": "PPE"}


def _from_form_tables(changes: dict) -> None:
    """The form's tables (team rows, corrective-action rows) also fill the matching summary fields."""
    members = [m for m in (changes.get("team_members") or []) if (m.get("name") or "").strip()]
    if "team_members" in changes:
        changes["team_members"] = members
    if members:
        changes.setdefault("investigation_team", "; ".join(
            f"{m['name']} ({m['job_title']})" if m.get("job_title") else m["name"] for m in members))
        changes.setdefault("team_details", "; ".join(
            ", ".join(p for p in (m["name"], m.get("job_title"), m.get("date")) if p) for m in members))
        days = [d for d in (_parse_day(m.get("date")) for m in members) if d]
        if not changes.get("assignment_date"):
            changes["assignment_date"] = min(days) if days else datetime.utcnow()
    items = [a for a in (changes.get("action_items") or []) if (a.get("action") or "").strip()]
    if "action_items" in changes:
        changes["action_items"] = items
    if items:
        changes.setdefault("corrective_action", "\n".join(
            a["action"] + (f" [{CONTROL_LABELS.get(a.get('control'), a.get('control'))}]" if a.get("control") else "")
            + (f" by {a['by_whom']}" if a.get("by_whom") else "") + (f", by {a['by_when']}" if a.get("by_when") else "")
            for a in items))
        owners = [a["by_whom"] for a in items if a.get("by_whom")]
        if owners:
            changes.setdefault("responsible_person", ", ".join(dict.fromkeys(owners)))
        dues = [d for d in (_parse_day(a.get("by_when")) for a in items) if d]
        if dues:
            changes.setdefault("due_date", max(dues))


def _apply_workflow(incident: Incident, workflow_data, user: User, request: Request, db: Session) -> None:
    changes = workflow_data if isinstance(workflow_data, dict) else workflow_data.model_dump(exclude_unset=True)
    if user.role == "operations":
        if set(changes) != {"operations_manager_comment"} or not _is_fatal(incident):
            raise HTTPException(status_code=403, detail="Operations Managers may only comment on fatal incidents")
    elif user.role not in WORKFLOW_ROLES:
        raise HTTPException(status_code=403, detail="Only SHE users may update the incident workflow")
    workflow = incident._workflow
    if workflow is None:
        workflow = IncidentWorkflow(incident_id=incident.id)
        db.add(workflow)
        db.flush()
    previous = workflow.status
    _from_form_tables(changes)
    if user.role != "operations":
        _validate_workflow(incident, workflow, changes)
    for key, value in changes.items():
        setattr(workflow, key, value)
    if changes.get("status") == "closed":
        workflow.closed_at = datetime.utcnow()
        workflow.closed_by_id = user.id
        incident.resolved = True
    if changes.get("status") == REPORT_FINALISED:
        incident.resolved = True
    db.commit()
    db.refresh(workflow)
    details = json.dumps({"previous_stage": previous, "new_stage": workflow.status,
                          "changed_fields": sorted(changes)})
    log_action(db=db, user=user, action="INCIDENT_WORKFLOW_CHANGED", resource="incidents",
               resource_id=incident.id, details=details, ip_address=request.client.host)


# Get all incidents
@router.get("/", response_model=List[IncidentResponse])
def get_all_incidents(
    response: Response,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Incident)
    if current_user.role == "site_manager":
        query = query.filter(Incident.site_id == current_user.site_id)
    mine = region_site_ids(db, current_user)
    if mine is not None:  # a regional manager sees the incidents at the sites in their region
        query = query.filter(Incident.site_id.in_(mine or [0]))
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
    assert_site_visible(db, current_user, incident.site_id)
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
    assert_site_visible(db, current_user, incident.site_id)
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
    assert_site_visible(db, current_user, incident.site_id)
    changes = incident_data.model_dump(exclude_unset=True)
    workflow_data = changes.pop("incident_workflow", None)
    intake = changes.pop("incident_intake", None)
    if workflow_data is not None:
        _apply_workflow(incident, workflow_data, current_user, request, db)
    if current_user.role == "operations" and (intake is not None or changes):
        raise HTTPException(status_code=403, detail="Operations Managers may only comment on fatal incidents")
    if intake is not None:
        if current_user.role != "site_manager" and current_user.role not in WORKFLOW_ROLES:
            raise HTTPException(status_code=403, detail="You don't have permission to update incident intake")
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
    assert_site_visible(db, user, incident.site_id)
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
    if current_user.role not in EVIDENCE_ROLES:
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
