"""One-off repair for text saved as '&amp;' / '&lt;' / '&gt;' by the old sanitiser."""
import html

from sqlalchemy import String, Text, select, update

SKIP_COLUMNS = {"password", "email", "user_email", "token"}
MARKERS = ("&amp;", "&lt;", "&gt;", "&quot;", "&#x27;", "&#39;")


def _targets(metadata):
    for table in metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, (String, Text)) and col.name not in SKIP_COLUMNS and not col.primary_key:
                yield table, col


def fix_escaped_text(db, metadata, apply: bool = False) -> dict:
    """Return {"table.column": rows_fixed}. Nothing is written unless apply=True."""
    report = {}
    for table, col in _targets(metadata):
        pk = list(table.primary_key.columns)
        if len(pk) != 1:
            continue
        rows = db.execute(select(pk[0], col).where(col.isnot(None))).all()
        changed = 0
        for pk_value, text in rows:
            if not isinstance(text, str) or not any(m in text for m in MARKERS):
                continue
            fixed = html.unescape(text)
            if fixed != text:
                changed += 1
                if apply:
                    db.execute(update(table).where(pk[0] == pk_value).values({col.name: fixed}))
        if changed:
            report[f"{table.name}.{col.name}"] = changed
    if apply:
        db.commit()
    return report
