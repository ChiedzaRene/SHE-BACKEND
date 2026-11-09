"""Start the portal's records afresh, keeping the user accounts and the sites, and add site and SHE accounts.

Everything else is emptied: incidents and their investigations, corrective actions, inspections, fire
equipment checks, talks, trainings, licences, hours worked, SHE files, notifications and the audit log.
App settings (the LTIFR limit) are kept. Numbering starts again from 1 (the first incident is INC-1).

Run it on the server (Render Shell), where DATABASE_URL and SECRET_KEY are already set:

    python reset_data.py            # shows what would be deleted and added; changes nothing
    python reset_data.py --yes      # does it, in one transaction (all or nothing)

The new accounts' first password is asked for (it is not stored in this file); each new person must
choose their own password when they first sign in. Accounts that already exist are left as they are.
"""
import argparse
import getpass
import importlib
import os
import pkgutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import func, inspect, text  # noqa: E402

import models  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402

# every model module, so every table is known
for mod in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"models.{mod.name}")

from models.site import Site  # noqa: E402
from models.user import User  # noqa: E402

KEEP = {"users", "sites", "app_settings"}

# email -> (site name, or None for an account that covers every site), role
NEW_ACCOUNTS = {
    "energycentre@glowpetroleum.com": ("Energy Centre", "site_manager"),
    "northgate@glowpetroleum.com": ("Northgate Centre", "site_manager"),
    "cathedral@glowpetroleum.com": ("Cathedral Centre", "site_manager"),
    "greatdyke@glowpetroleum.com": ("Great Dyke", "site_manager"),
    "treasurecentre@glowpetroleum.com": ("Treasure Centre", "site_manager"),
    "westward@glowpetroleum.com": ("Westward Centre", "site_manager"),
    "expectationscentre@glowpetroleum.com": ("Expectations", "site_manager"),
    "westend@glowpetroleum.com": ("Westend Centre", "site_manager"),
    "stopover@glowpetroleum.com": ("Stopover Centre", "site_manager"),
    "transitcentre@glowpetroleum.com": ("Transit Centre", "site_manager"),
    "resortcentre@glowpetroleum.com": ("Resort Centre", "site_manager"),
    "she@glowpetroleum.com": (None, "she_team"),
}


def tables_to_empty(existing: set) -> list:
    """Child tables before the tables they point at, so nothing is left pointing at a deleted row."""
    return [t for t in reversed(Base.metadata.sorted_tables) if t.name not in KEEP and t.name in existing]


def plan_accounts(db) -> tuple:
    sites = {s.name.strip().lower(): s for s in db.query(Site).all()}
    to_add, skipped, problems = [], [], []
    for email, (site_name, role) in NEW_ACCOUNTS.items():
        if db.query(User).filter(func.lower(User.email) == email).first():
            skipped.append(email)
            continue
        site = sites.get(site_name.lower()) if site_name else None
        if site_name and site is None:
            problems.append(f"{email}: no site called \"{site_name}\"")
            continue
        to_add.append((email, role, site))
    return to_add, skipped, problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="really delete and add (otherwise only show the plan)")
    args = parser.parse_args()

    existing = set(inspect(engine).get_table_names())
    empty = tables_to_empty(existing)
    db = SessionLocal()
    try:
        print(f"Database: {engine.url.render_as_string(hide_password=True)}\n")
        print("Kept: " + ", ".join(sorted(KEEP & existing)))
        print(f"  {db.query(User).count()} user accounts, {db.query(Site).count()} sites\n")
        print("Emptied:")
        for t in empty:
            print(f"  {t.name:28} {db.execute(text(f'SELECT COUNT(*) FROM {t.name}')).scalar()} rows")
        to_add, skipped, problems = plan_accounts(db)
        print("\nAccounts to add:")
        for email, role, site in to_add:
            print(f"  {email:40} {role:13} {site.name if site else 'all sites'}")
        for email in skipped:
            print(f"  {email:40} already exists, left as it is")
        if problems:
            print("\nCan't continue:\n  " + "\n  ".join(problems))
            sys.exit(1)
        if not args.yes:
            print("\nNothing has been changed. Run again with --yes to do it.")
            return

        password = ""
        if to_add:
            password = getpass.getpass("First password for the new accounts: ")
            if len(password) < 8 or password != getpass.getpass("Type it again: "):
                print("The passwords don't match or are shorter than 8 characters. Nothing has been changed.")
                sys.exit(1)
        from services.auth_services import hash_password  # needs SECRET_KEY, set on the server

        for t in empty:
            db.execute(t.delete())
        for email, role, site in to_add:
            db.add(User(email=email, password=hash_password(password), role=role, site_id=site.id if site else None,
                        full_name=site.name if site else "SHE Team", is_active=True, must_change_password=True))
        db.commit()
    except Exception:
        db.rollback()
        print("\nSomething went wrong, so nothing has been changed.")
        raise
    finally:
        db.close()

    # numbering starts again from 1 (PostgreSQL keeps its counters after rows are deleted)
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            for t in empty:
                if "id" in t.c:
                    conn.execute(text("SELECT setval(pg_get_serial_sequence(:t, 'id'), 1, false)"), {"t": t.name})
    print(f"\nDone: {len(empty)} tables emptied, {len(to_add)} accounts added. "
          "New accounts choose their own password when they first sign in.")


if __name__ == "__main__":
    main()
