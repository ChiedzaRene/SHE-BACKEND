"""The licences every site must hold, their status, and the reminders before they are due."""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models.site import Site
from models.site_licence import SiteLicence
from services.clock import local_today
from services.notifications import notify, site_managers, team

# key -> (name, who issues it)
LICENCE_TYPES = {
    "council_shop": ("Council shop licence", "City Council"),
    "fire_brigade": ("Fire brigade licence", "Fire Brigade"),
    "ema_septic": ("EMA septic tank waste discharge licence", "EMA"),
    "ema_air": ("EMA air emission licence", "EMA"),
    "hazardous_substances": ("Hazardous substance storage and sale licence", "EMA"),
    "council_trade_effluent": ("Council trade effluent licence", "City Council"),
    "ema_eia": ("Environmental Impact Assessment (EIA) licence", "EMA"),
}
FIRST_REMINDER_DAYS = 90   # about three months before
SECOND_REMINDER_DAYS = 30  # about a month before

# Licences with their own rhythm. An EIA licence is renewed every quarter: it is uploaded by the SHE team,
# runs for three months, and is reminded about a month and two weeks before it expires.
REMINDER_DAYS = {"ema_eia": (30, 14)}
VALID_MONTHS = {"ema_eia": 3}
SHE_ONLY = {"ema_eia"}
SHE_ROLES = ("she_team", "she_officer", "admin", "super_admin")

_WINDOW_NAMES = {90: "3 months", 30: "a month", 14: "2 weeks", 7: "a week"}


def reminder_days(licence_type: Optional[str] = None) -> tuple:
    """(first, second) reminder: how many days before expiry each is sent."""
    return REMINDER_DAYS.get(licence_type, (FIRST_REMINDER_DAYS, SECOND_REMINDER_DAYS))


def may_upload(user, licence_type: str) -> bool:
    return licence_type not in SHE_ONLY or user.role in SHE_ROLES


def status_of(expiry: Optional[date], today: date, licence_type: Optional[str] = None) -> str:
    """valid | due_3_months (first reminder window) | due_1_month (second window) | expired | missing"""
    if expiry is None:
        return "missing"
    first, second = reminder_days(licence_type)
    days = (expiry - today).days
    if days < 0:
        return "expired"
    if days <= second:
        return "due_1_month"
    if days <= first:
        return "due_3_months"
    return "valid"


def status_label(status: str, licence_type: Optional[str] = None) -> str:
    first, second = reminder_days(licence_type)
    return {
        "valid": "Valid", "expired": "Expired", "missing": "Not recorded",
        "due_3_months": f"Due within {_WINDOW_NAMES.get(first, f'{first} days')}",
        "due_1_month": f"Due within {_WINDOW_NAMES.get(second, f'{second} days')}",
    }[status]


def _when(d: date) -> str:
    return d.strftime("%d %B %Y").lstrip("0")


def send_reminders(db: Session, today: Optional[date] = None) -> int:
    """Tell the site's managers and the SHE team about licences coming due; each reminder is sent once."""
    today = today or local_today()
    now = datetime.now(timezone.utc)
    sent = 0
    sites = {s.id: s for s in db.query(Site).all()}
    she = team(db)
    for lic in db.query(SiteLicence).filter(SiteLicence.superseded_by.is_(None)).all():
        site = sites.get(lic.site_id)
        if not site:
            continue
        days = (lic.expiry_date - today).days
        name = LICENCE_TYPES.get(lic.licence_type, (lic.licence_type,))[0]
        first_days, second_days = reminder_days(lic.licence_type)
        message = None
        if days < 0 and not lic.reminded_expired:
            lic.reminded_expired = lic.reminded_30 = lic.reminded_90 = now
            title = f"{name} for {site.name} has expired"
            message = f"It expired on {_when(lic.expiry_date)}. Renew it and record the new licence."
            kind = "licence_expired"
        elif 0 <= days <= second_days and not lic.reminded_30:
            lic.reminded_30 = lic.reminded_90 = now
            title = f"{name} for {site.name} is due in {days} day{'s' if days != 1 else ''}"
            message = f"It must be renewed and paid by {_when(lic.expiry_date)}."
            kind = "licence_due"
        elif second_days < days <= first_days and not lic.reminded_90:
            lic.reminded_90 = now
            title = f"{name} for {site.name} is due in {_WINDOW_NAMES.get(first_days, f'{days} days')}"
            message = f"It must be renewed and paid by {_when(lic.expiry_date)}."
            kind = "licence_due"
        if message is None:
            continue
        db.commit()
        notify(db, she + site_managers(db, site.id), kind=kind, title=title, message=message,
               link="/legal", resource="licences", resource_id=lic.id)
        sent += 1
    return sent
