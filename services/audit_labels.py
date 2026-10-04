"""Plain-English names for the codes in the audit log, so people don't have to read CREATE_INCIDENT."""

ACTION_LABELS = {
    "CREATE_INCIDENT": "Incident logged",
    "UPDATE_INCIDENT": "Incident updated",
    "CREATE_CORRECTIVE_ACTION": "Corrective action created",
    "UPDATE_CORRECTIVE_ACTION": "Corrective action updated",
    "RESOLVE_CORRECTIVE_ACTION": "Corrective action resolved",
    "DELETE_CORRECTIVE_ACTION": "Corrective action deleted",
    "CREATE_AUDIT": "Audit created",
    "UPDATE_AUDIT": "Audit updated",
    "CREATE_LEGAL_RECORD": "Legal record created",
    "UPDATE_LEGAL_RECORD": "Legal record updated",
    "CREATE_TRAINING": "Training recorded",
    "UPDATE_TRAINING": "Training updated",
    "DELETE_TRAINING": "Training deleted",
    "CREATE_SITE": "Site created",
    "UPDATE_SITE": "Site updated",
    "DELETE_SITE": "Site deleted",
    "UPSERT_SITE_HOURS": "Hours worked entered",
    "CREATE_INSPECTION": "Inspection recorded",
    "UPDATE_INSPECTION": "Inspection updated",
    "DELETE_INSPECTION": "Inspection deleted",
    "CREATE_SCORECARD": "Legal scorecard submitted",
    "DELETE_SCORECARD": "Legal scorecard deleted",
    "LOGIN": "Signed in",
    "LOGIN_FAILED": "Failed sign-in attempt",
    "CREATE_USER": "User created",
    "UPDATE_USER": "User updated",
    "DELETE_USER": "User deleted",
    "RESET_PASSWORD": "Password reset by an admin",
    "CHANGE_PASSWORD": "Password changed by the user",
    "UPDATE_PROFILE": "Name changed by the user",
    "UPDATE_SETTINGS": "Settings changed",
    "EXPORT_REPORT": "Report downloaded",
}

RESOURCE_LABELS = {
    "incidents": "Incidents",
    "corrective_actions": "Corrective actions",
    "audits": "Audits",
    "legal": "Legal",
    "trainings": "Trainings",
    "sites": "Sites",
    "site_hours": "Hours worked",
    "users": "Users",
    "settings": "Settings",
    "reports": "Reports",
    "inspections": "Inspections",
    "scorecards": "Legal scorecards",
    "auth": "Sign-in",
    "audit_logs": "Audit log",
}


def _humanize(code: str) -> str:
    return (code or "").replace("_", " ").strip().capitalize()


def action_label(code: str) -> str:
    return ACTION_LABELS.get(code) or _humanize(code)


def resource_label(code: str) -> str:
    return RESOURCE_LABELS.get(code) or _humanize(code)
