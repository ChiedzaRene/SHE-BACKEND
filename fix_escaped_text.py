"""Repair text such as 'Fuel &amp; Lubricants' that was stored garbled.

    python fix_escaped_text.py          # shows what WOULD change, writes nothing
    python fix_escaped_text.py --apply  # makes the change (take a backup first: python backup.py)
"""
import sys

import main  # noqa: F401  (loads every table definition)
from database import Base, SessionLocal
from services.text_cleanup import fix_escaped_text

if __name__ == "__main__":
    apply = "--apply" in sys.argv
    db = SessionLocal()
    try:
        report = fix_escaped_text(db, Base.metadata, apply=apply)
    finally:
        db.close()
    if not report:
        print("Nothing to fix.")
    for name, n in report.items():
        print(f"{name}: {n} row(s) {'fixed' if apply else 'would be fixed'}")
    if report and not apply:
        print("\nRun again with --apply to make these changes.")
