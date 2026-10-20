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
}
FIRST_REMINDER_DAYS = 90   # about three months before
SECOND_REMINDER_DAYS = 30  # about a month before


def status_of(expiry: Optional[date], today: date) -> str:
    """valid | due_3_months | due_1_month | expired | missing"""
    if expiry is None:
        return "missing"
    days = (expiry - today).days
    if days < 0:
        return "expired"
    if days <= SECOND_REMINDER_DAYS:
        return "due_1_month"
    if days <= FIRST_REMINDER_DAYS:
        return "due_3_months"
    return "valid"


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
        message = None
        if days < 0 and not lic.reminded_expired:
            lic.reminded_expired = lic.reminded_30 = lic.reminded_90 = now
            title = f"{name} for {site.name} has expired"
            message = f"It expired on {_when(lic.expiry_date)}. Renew it and record the new licence."
            kind = "licence_expired"
        elif 0 <= days <= SECOND_REMINDER_DAYS and not lic.reminded_30:
            lic.reminded_30 = lic.reminded_90 = now
            title = f"{name} for {site.name} is due in {days} day{'s' if days != 1 else ''}"
            message = f"It must be renewed and paid by {_when(lic.expiry_date)}."
            kind = "licence_due"
        elif SECOND_REMINDER_DAYS < days <= FIRST_REMINDER_DAYS and not lic.reminded_90:
            lic.reminded_90 = now
            title = f"{name} for {site.name} is due in 3 months"
            message = f"It must be renewed and paid by {_when(lic.expiry_date)}."
            kind = "licence_due"
        if message is None:
            continue
        db.commit()
        notify(db, she + site_managers(db, site.id), kind=kind, title=title, message=message,
               link="/legal", resource="licences", resource_id=lic.id)
        sent += 1
    return sent
