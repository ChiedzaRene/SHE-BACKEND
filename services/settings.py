"""Admin-editable settings. Defaults apply until an admin changes them."""
from sqlalchemy.orm import Session

from models.app_setting import AppSetting
from services.safety_metrics import LTIFR_LIMIT, RATE_BASIS_HOURS, TRIR_LIMIT

DEFAULTS = {"trir_limit": TRIR_LIMIT, "ltifr_limit": LTIFR_LIMIT}


def get_safety_limits(db: Session) -> dict:
    """The TRIR/LTIFR limits above which a site is flagged. Bad stored values fall back to defaults."""
    limits = dict(DEFAULTS)
    for row in db.query(AppSetting).filter(AppSetting.key.in_(list(DEFAULTS))):
        try:
            value = float(row.value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            limits[row.key] = value
    return limits


def safety_targets_payload(db: Session) -> dict:
    """Editable limits plus the fixed reporting rules, so screens can show how rates are calculated."""
    limits = get_safety_limits(db)
    return {
        **limits,
        "rate_basis_hours": RATE_BASIS_HOURS,
        "recordable_rule": "An incident of type 'injury' is recordable.",
        "lost_time_rule": "A lost-time injury is a recordable injury with lost days above 0.",
    }


def set_safety_limits(db: Session, user_id: int, trir_limit: float, ltifr_limit: float) -> None:
    for key, value in (("trir_limit", trir_limit), ("ltifr_limit", ltifr_limit)):
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value, row.updated_by = repr(float(value)), user_id
        else:
            db.add(AppSetting(key=key, value=repr(float(value)), updated_by=user_id))
    db.commit()
