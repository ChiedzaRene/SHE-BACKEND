"""Admin-editable settings. Defaults apply until an admin changes them."""
from sqlalchemy.orm import Session

from models.app_setting import AppSetting
from services.safety_metrics import LTIFR_LIMIT, RATE_BASIS_HOURS

DEFAULTS = {"ltifr_limit": LTIFR_LIMIT}


def get_safety_limits(db: Session) -> dict:
    """The LTIFR limit above which a site is flagged. Bad stored values fall back to defaults."""
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


BASIS_KEY = "rate_basis_hours"


def rescale_saved_limits(db: Session) -> list:
    """A limit an admin saved on an earlier rate basis is converted once to the current basis.

    LTIFR was per 200,000 hours before the basis became 1,000,000, so a saved 0.5 becomes 2.5.
    """
    marker = db.query(AppSetting).filter(AppSetting.key == BASIS_KEY).first()
    old_basis = float(marker.value) if marker else 200_000.0
    notes = []
    if old_basis != RATE_BASIS_HOURS:
        for row in db.query(AppSetting).filter(AppSetting.key.in_(list(DEFAULTS))):
            try:
                value = float(row.value)
            except (TypeError, ValueError):
                continue
            row.value = repr(round(value * RATE_BASIS_HOURS / old_basis, 4))
            notes.append(f"{row.key} {value:g} -> {row.value} (per {RATE_BASIS_HOURS:,} hours)")
    if marker:
        marker.value = str(RATE_BASIS_HOURS)
    else:
        db.add(AppSetting(key=BASIS_KEY, value=str(RATE_BASIS_HOURS)))
    db.commit()
    return notes


def set_safety_limits(db: Session, user_id: int, ltifr_limit: float) -> None:
    for key, value in (("ltifr_limit", ltifr_limit),):
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value, row.updated_by = repr(float(value)), user_id
        else:
            db.add(AppSetting(key=key, value=repr(float(value)), updated_by=user_id))
    db.commit()
