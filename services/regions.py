"""The regions sites are grouped into. Each region is looked after by its regional manager(s)."""
from typing import Optional

REGIONS = ["Harare East", "Harare West", "Midlands", "Matabeleland", "South East"]


def canonical(name: Optional[str]) -> Optional[str]:
    """The region as it is written in REGIONS (any case or spacing), or None if it isn't one of them."""
    wanted = " ".join((name or "").split()).lower()
    return next((r for r in REGIONS if r.lower() == wanted), None)


def choose_message() -> str:
    return f"Choose one of the regions: {', '.join(REGIONS)}."
