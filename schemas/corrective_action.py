from datetime import datetime
from typing import Optional, Union
import bleach
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Strips all HTML/script tags from user-provided text inputs."""
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True).strip()
    return value


class CorrectiveActionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    incident_id: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("incident_id", "incidentId"),
    )
    site_id: Optional[int] = Field(default=None, gt=0)
    description: Optional[str] = Field(default=None, max_length=2000)
    action_taken: Optional[str] = Field(
        default=None,
        max_length=1000,
        validation_alias=AliasChoices("action_taken", "actionTaken"),
    )
    assigned_to: Optional[Union[int, str]] = Field(
        default=None,
        validation_alias=AliasChoices("assigned_to", "assignedTo"),
    )
    designation: Optional[str] = Field(default="Safety", max_length=100)
    status: Optional[str] = Field(
        default="open",
        pattern="^(open|in_progress|resolved|closed)$",
    )
    priority: Optional[str] = Field(
        default="medium",
        pattern="^(low|medium|high|critical)$",
    )
    due_date: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("due_date", "dueDate"),
    )

    @field_validator(
        "description", "action_taken", "designation", "status", "priority", mode="before"
    )
    @classmethod
    def sanitize_string_fields(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)

    @field_validator("assigned_to", mode="before")
    @classmethod
    def sanitize_assigned_to(cls, value: Optional[Union[int, str]]) -> Optional[Union[int, str]]:
        if isinstance(value, str):
            return sanitize_text(value)
        return value


class CorrectiveActionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    site_id: Optional[int] = Field(default=None, gt=0)
    description: Optional[str] = Field(default=None, max_length=2000)
    action_taken: Optional[str] = Field(
        default=None,
        max_length=1000,
        validation_alias=AliasChoices("action_taken", "actionTaken"),
    )
    assigned_to: Optional[Union[int, str]] = Field(
        default=None,
        validation_alias=AliasChoices("assigned_to", "assignedTo"),
    )
    designation: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(
        default=None,
        pattern="^(open|in_progress|resolved|closed)$",
    )
    priority: Optional[str] = Field(
        default=None,
        pattern="^(low|medium|high|critical)$",
    )
    due_date: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("due_date", "dueDate"),
    )
    date_resolved: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("date_resolved", "dateResolved"),
    )

    @field_validator(
        "description", "action_taken", "designation", "status", "priority", mode="before"
    )
    @classmethod
    def sanitize_string_fields(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)

    @field_validator("assigned_to", mode="before")
    @classmethod
    def sanitize_assigned_to(cls, value: Optional[Union[int, str]]) -> Optional[Union[int, str]]:
        if isinstance(value, str):
            return sanitize_text(value)
        return value


class CorrectiveActionResolve(BaseModel):
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)
    is_successful: str = Field(..., pattern="^(yes|no)$")

    @field_validator("resolution_notes", "is_successful", mode="before")
    @classmethod
    def sanitize_resolution_inputs(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value)


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