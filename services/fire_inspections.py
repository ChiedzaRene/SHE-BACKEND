"""The fire equipment checks sites do themselves: the checklist, when the next one is due, and reminders."""
import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models.fire_inspection import FireInspection
from models.site import Site
from services.clock import local_today
from services.notifications import notify, site_managers, team

FORTNIGHT_DAYS = 14
SERVICE_MONTHS = 6
SERVICE_REMINDER_DAYS = 14   # the SHE team hears two weeks before a service and refill is due

KINDS = {
    "fortnightly": "Fortnightly fire equipment inspection",
    "service_refill": "Fire extinguisher service and refill",
}
RESULTS = ("C", "NC", "NA")  # conforming, not conforming, not applicable

# Fortnightly Fire Equipment Inspection Checklist, GP-SHE/OPR/10/02: (section, [(group, [(key, item)])])
CHECKLIST = [
    ("Fire extinguishers", [
        ("Location", [
            ("fe_visible", "Fire extinguisher is visible and free from obstructions"),
            ("fe_demarcated", "Position of the fire extinguisher is clearly demarcated"),
            ("fe_position", "Fire extinguisher is still in its designated position"),
            ("fe_accessible", "Fire extinguisher is easily accessible"),
        ]),
        ("Physical state", [
            ("fe_label", "Label is readable"),
            ("fe_cylinder", "Cylinder is free from corrosion, dents and damage"),
            ("fe_hose_connection", "Connection between the hose and the cylinder is secure"),
            ("fe_clean", "Fire extinguisher is clean, free from dust and spider webs"),
        ]),
        ("Service tag and labels", [
            ("fe_tag", "Service tag is present"),
            ("fe_label_info", "Information on the label is visible"),
            ("fe_tag_history", "Service tag shows the service history (last and next service)"),
            ("fe_tag_contractor", "Service tag shows the service contractor's contact details or address"),
            ("fe_instructions", "Operating instructions are legible and facing outward"),
        ]),
        ("Pressure indicator", [
            ("fe_gauge", "Pressure gauge is present and in good condition"),
            ("fe_pointer", "Pointer is on the green mark"),
            ("fe_range", "Pressure gauge is in the operable range"),
            ("fe_lens", "Glass lens is not obstructed"),
        ]),
        ("Discharge nozzle", [
            ("fe_outlet", "Outlet hose is in good condition and not blocked"),
            ("fe_no_leaks", "No cracks or leaks in the hose or nozzle"),
        ]),
        ("Handle and release lever", [
            ("fe_seal", "Tamper seal is in place"),
            ("fe_pin_seal", "Locking pin is secured by the tamper seal"),
            ("fe_safety_pin", "Handle has a safety pin"),
        ]),
        ("Support bracket", [
            ("fe_bracket", "Bracket is strong enough to hold the fire extinguisher"),
        ]),
    ]),
    ("Sand buckets", [
        ("Sand buckets", [
            ("sb_dry", "Sand is dry"),
            ("sb_rubbish", "No rubbish in the sand"),
            ("sb_handles", "Handles are secure and not corroded"),
            ("sb_condition", "Bucket is in good condition: no dents or sharp edges"),
        ]),
    ]),
    ("Fire hose reels", [
        ("Fire hose reels", [
            ("hr_position", "In its designated position, unobstructed, with legible instructions"),
            ("hr_condition", "No damage, corrosion, faults or obstruction"),
            ("hr_drum", "Drum rotates freely"),
            ("hr_leaks", "No leakage in the area"),
            ("hr_pressure", "Enough water pressure"),
            ("hr_valves", "Valves open and close properly"),
        ]),
    ]),
]
ITEMS = {key: text for _, groups in CHECKLIST for _, items in groups for key, text in items}


def checklist() -> list:
    return [
        {"section": section, "groups": [
            {"group": group, "items": [{"key": k, "text": t} for k, t in items]} for group, items in groups
        ]}
        for section, groups in CHECKLIST
    ]


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def default_next_due(kind: str, inspection_date: date) -> date:
    if kind == "fortnightly":
        return inspection_date + timedelta(days=FORTNIGHT_DAYS)
    return add_months(inspection_date, SERVICE_MONTHS)


def latest(db: Session, site_id: int, kind: str) -> Optional[FireInspection]:
    return (
        db.query(FireInspection)
        .filter(FireInspection.site_id == site_id, FireInspection.kind == kind)
        .order_by(FireInspection.inspection_date.desc(), FireInspection.id.desc())
        .first()
    )


def _when(d: date) -> str:
    return d.strftime("%d %B %Y").lstrip("0")


def send_reminders(db: Session, today: Optional[date] = None) -> int:
    """Two weeks before a site's next service and refill, tell the SHE team and the site (once)."""
    today = today or local_today()
    sent = 0
    she = None
    for site in db.query(Site).all():
        last = latest(db, site.id, "service_refill")
        if not last or last.reminded_at or (last.next_due - today).days > SERVICE_REMINDER_DAYS:
            continue
        last.reminded_at = datetime.now(timezone.utc)
        db.commit()
        days = (last.next_due - today).days
        if days < 0:
            title = f"Fire extinguisher service and refill for {site.name} is overdue"
        else:
            title = f"Fire extinguisher service and refill for {site.name} is due in {days} day{'s' if days != 1 else ''}"
        she = team(db) if she is None else she
        notify(db, she + site_managers(db, site.id), kind="fire_service_due", title=title,
               message=f"The next service and refill is due on {_when(last.next_due)}.",
               link="/inspections?tab=fire", resource="fire_inspections", resource_id=last.id)
        sent += 1
    return sent
