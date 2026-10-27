"""Formatted text from the report editor (bold, italic, underline, lists, paragraphs).

Everything else (scripts, styles, links, attributes) is stripped, so it is safe to show as HTML.
"""
import html as html_lib
import re
from typing import Optional

import bleach

ALLOWED_TAGS = ["p", "br", "div", "b", "strong", "i", "em", "u", "ul", "ol", "li"]


def clean_html(value: Optional[str], max_length: int = 20000) -> Optional[str]:
    if value is None:
        return None
    html = bleach.clean(str(value)[: max_length * 2], tags=ALLOWED_TAGS, attributes={}, strip=True,
                        strip_comments=True).strip()
    if not plain_text(html):
        return None
    return html[:max_length]


def as_text(value: Optional[str]) -> str:
    """Formatted (or older plain) text as plain words, with characters such as & and < as typed."""
    return html_lib.unescape(plain_text(value)) if value else ""


def as_safe_html(value: Optional[str]) -> Optional[str]:
    """Stored text ready to show as HTML. Older plain text keeps its line breaks; anything else is cleaned again."""
    if not value:
        return None
    return clean_html(str(value).replace("\r\n", "\n").replace("\n", "<br>"))


def plain_text(html: Optional[str]) -> str:
    """The words without the formatting (for notifications, search and length checks)."""
    text = re.sub(r"<(br|/p|/div|/li)\s*/?>", " ", html or "", flags=re.I)
    text = bleach.clean(text, tags=[], strip=True)
    return " ".join(text.replace("&nbsp;", " ").split())
