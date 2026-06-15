from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Optional, Union
from datetime import datetime


class CorrectiveActionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    incident_id: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("incident_id", "incidentId")
    )
    site_id: Optional[int] = None
    description: Optional[str] = None
    action_taken: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("action_taken", "actionTaken"),
    )
    assigned_to: Optional[Union[int, str]] = Field(
        default=None,
        validation_alias=AliasChoices("assigned_to", "assignedTo"),
    )
    designation: Optional[str] = "Safety"
    status: Optional[str] = "open"
    priority: Optional[str] = "medium"
    due_date: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("due_date", "dueDate")
    )


class CorrectiveActionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    site_id: Optional[int] = None
    description: Optional[str] = None
    action_taken: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("action_taken", "actionTaken"),
    )
    assigned_to: Optional[Union[int, str]] = Field(
        default=None,
        validation_alias=AliasChoices("assigned_to", "assignedTo"),
    )
    designation: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("due_date", "dueDate")
    )
    date_resolved: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("date_resolved", "dateResolved"),
    )


# New schema specifically for resolution
class CorrectiveActionResolve(BaseModel):
    resolution_notes: Optional[str] = None
    is_successful: str  # "yes" or "no"


class CorrectiveActionResponse(BaseModel):
    id: int
    incident_id: Optional[int] = None
    site_id: Optional[int] = None
    description: Optional[str] = None
    action_taken: str
    assigned_to: str
    designation: Optional[str] = None
    status: str
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    date_resolved: Optional[datetime] = None
    created_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    resolved_by: Optional[str] = None
    is_successful: Optional[str] = None

    class Config:
        from_attributes = True