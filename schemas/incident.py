from datetime import datetime
from datetime import timedelta
from typing import Any, Dict, List, Literal, Optional
import html
import bleach
from pydantic import BaseModel, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips HTML and script tags from text inputs to prevent XSS attacks."""
    if isinstance(value, str):
        return html.unescape(bleach.clean(value, tags=[], strip=True)).strip()
    return value


def check_not_future(value: Optional[datetime]) -> Optional[datetime]:
    # Clients send local wall-clock time (no timezone); a day of slack covers any UTC offset.
    if value is not None and value > datetime.utcnow() + timedelta(days=1):
        raise ValueError("occurred_at cannot be in the future")
    return value


class IncidentCreate(BaseModel):
    site_id: int = Field(..., gt=0, description="Site ID must be a positive integer")
    type: str = Field(..., min_length=2, max_length=100)
    description: str = Field(..., min_length=5, max_length=3000)
    severity: str = Field(
        ...,
        pattern="^(Low|Medium|High|Critical|Fatal|low|medium|high|critical|fatal)$",
        description="Severity level must be Low, Medium, High, or Critical",
    )
    total_hours_worked: Optional[int] = Field(default=0, ge=0)
    lost_time_days: Optional[int] = Field(default=0, ge=0)
    # When the incident actually happened; LTIFR files it under this month
    occurred_at: Optional[datetime] = None
    # Name of the person hurt (injuries only)
    injured_person: Optional[str] = Field(default=None, max_length=150)
    # What will be done about it (separate from the description, which can't be changed)
    action_plan: Optional[str] = Field(default=None, max_length=5000)
    incident_intake: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("type", "description", "severity", "injured_person", "action_plan", mode="before")
    @classmethod
    def clean_string_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)

    @field_validator("occurred_at")
    @classmethod
    def occurred_not_future(cls, value: Optional[datetime]) -> Optional[datetime]:
        return check_not_future(value)


class IncidentUpdate(BaseModel):
    type: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, min_length=5, max_length=3000)
    severity: Optional[str] = Field(
        default=None,
        pattern="^(Low|Medium|High|Critical|Fatal|low|medium|high|critical|fatal)$",
    )
    resolved: Optional[bool] = None
    total_hours_worked: Optional[int] = Field(default=None, ge=0)
    lost_time_days: Optional[int] = Field(default=None, ge=0)
    occurred_at: Optional[datetime] = None
    # Name of the person hurt (injuries only)
    injured_person: Optional[str] = Field(default=None, max_length=150)
    # What will be done about it (separate from the description, which can't be changed)
    action_plan: Optional[str] = Field(default=None, max_length=5000)
    incident_intake: Optional[Dict[str, Any]] = None
    incident_workflow: Optional["IncidentWorkflowUpdate"] = None

    @field_validator("type", "description", "severity", "injured_person", "action_plan", mode="before")
    @classmethod
    def clean_string_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)

    @field_validator("occurred_at")
    @classmethod
    def occurred_not_future(cls, value: Optional[datetime]) -> Optional[datetime]:
        return check_not_future(value)


class IncidentResponse(BaseModel):
    id: int
    site_id: int
    user_id: int
    type: str
    description: str
    severity: str
    resolved: bool
    date_time: Optional[datetime] = None
    total_hours_worked: Optional[int] = 0
    lost_time_days: Optional[int] = 0
    occurred_at: Optional[datetime] = None
    injured_person: Optional[str] = None
    action_plan: Optional[str] = None
    incident_intake: Dict[str, Any] = Field(default_factory=dict)
    incident_workflow: "IncidentWorkflowResponse" = Field(default_factory=lambda: IncidentWorkflowResponse())
    files: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        from_attributes = True


class TeamMember(BaseModel):
    """A row of the form's INVESTIGATION TEAM table. Team members are people with accounts."""
    user_id: Optional[int] = Field(None, gt=0)  # rows without a person are dropped
    name: str = Field("", max_length=150)  # filled in from the account
    job_title: Optional[str] = Field(None, max_length=150)
    date: Optional[str] = Field(None, max_length=20)

    @field_validator("name", "job_title", "date", mode="before")
    @classmethod
    def clean(cls, value):
        return sanitize_text(value)


# The form's hierarchy of control, most effective first
CONTROLS = Literal["elimination", "substitution", "isolation", "redesign", "administration", "ppe"]


class ActionItem(BaseModel):
    """A row of the form's CORRECTIVE ACTION table."""
    action: str = Field("", max_length=2000)  # blank rows are dropped
    control: Optional[CONTROLS] = None
    by_whom: Optional[str] = Field(None, max_length=150)
    by_when: Optional[str] = Field(None, max_length=20)

    @field_validator("action", "by_whom", "by_when", mode="before")
    @classmethod
    def clean(cls, value):
        return sanitize_text(value)


REPORT_TYPES = Literal[
    "preliminary_investigation",
    "interim_corrective_action",
    "full_investigation",
    "full_corrective_action",
]


class IncidentWorkflowUpdate(BaseModel):
    status: Optional[Literal["reported", "assigned", "investigating", "findings_recorded", "root_cause_recorded",
                             "actions_assigned", "closed"]] = None
    investigation_team: Optional[str] = Field(None, max_length=5000)
    team_details: Optional[str] = Field(None, max_length=5000)
    team_members: Optional[List[TeamMember]] = Field(None, max_length=20)
    assignment_date: Optional[datetime] = None
    evidence: Optional[str] = Field(None, max_length=10000)
    witness_reports: Optional[str] = Field(None, max_length=10000)
    supporting_documents: Optional[List[Dict[str, Any]]] = None
    sketches: Optional[str] = Field(None, max_length=10000)
    costs: Optional[str] = Field(None, max_length=5000)
    damage_payer: Optional[str] = Field(None, max_length=255)
    cost_usd: Optional[float] = Field(None, ge=0)
    causes: Optional[List[str]] = Field(None, max_length=3)
    root_cause: Optional[str] = Field(None, max_length=10000)
    corrective_action: Optional[str] = Field(None, max_length=10000)
    action_items: Optional[List[ActionItem]] = Field(None, max_length=20)
    responsible_person: Optional[str] = Field(None, max_length=255)
    due_date: Optional[datetime] = None
    lessons_learned: Optional[str] = Field(None, max_length=10000)
    report_type: Optional[REPORT_TYPES] = None
    report_dates: Optional[Dict[REPORT_TYPES, Optional[str]]] = None
    report_revised: Optional[bool] = None
    she_comment: Optional[str] = Field(None, max_length=10000)
    operations_manager_comment: Optional[str] = Field(None, max_length=10000)

    @field_validator("report_dates")
    @classmethod
    def clean_report_dates(cls, value):
        if value is None:
            return value
        return {k: (str(v)[:10] if v else None) for k, v in value.items()}

    @field_validator(
        "investigation_team", "team_details", "evidence", "witness_reports", "sketches", "costs",
        "damage_payer", "root_cause", "corrective_action", "responsible_person", "lessons_learned",
        "she_comment", "operations_manager_comment", mode="before"
    )
    @classmethod
    def clean_workflow_text(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


class IncidentWorkflowResponse(BaseModel):
    status: str = "reported"
    investigation_team: Optional[str] = None
    team_details: Optional[str] = None
    team_members: Optional[List[Dict[str, Any]]] = None
    action_items: Optional[List[Dict[str, Any]]] = None
    assignment_date: Optional[datetime] = None
    evidence: Optional[str] = None
    witness_reports: Optional[str] = None
    supporting_documents: Optional[List[Dict[str, Any]]] = None
    sketches: Optional[str] = None
    costs: Optional[str] = None
    damage_payer: Optional[str] = None
    cost_usd: Optional[float] = None
    causes: Optional[List[str]] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    responsible_person: Optional[str] = None
    due_date: Optional[datetime] = None
    lessons_learned: Optional[str] = None
    closed_at: Optional[datetime] = None
    closed_by_id: Optional[int] = None
    report_type: Optional[REPORT_TYPES] = None
    report_dates: Optional[Dict[str, Optional[str]]] = None
    report_revised: bool = False
    she_comment: Optional[str] = None
    operations_manager_comment: Optional[str] = None

    class Config:
        from_attributes = True



IncidentUpdate.model_rebuild()
IncidentResponse.model_rebuild()