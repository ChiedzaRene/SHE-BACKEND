import html
import bleach

def sanitize_text(text: str) -> str:
    """Strips HTML/script tags from user inputs to prevent XSS attacks."""
    if not text:
        return text
    return html.unescape(bleach.clean(text, tags=[], strip=True)).strip()