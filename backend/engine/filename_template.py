"""Filename template engine — {field} placeholder substitution."""

import re
import unicodedata
from typing import Dict, Optional

# Map template placeholder names to metadata dict keys
_FIELD_MAP = {
    "title": "title",
    "author": "authors",
    "authors": "authors",
    "publisher": "publisher",
    "isbn": "isbn",
    "ss_code": "ss_code",
    "source": "download_source",
    "download_source": "download_source",
    "year": "year",
    "book_id": "book_id",
}

def _sanitize(s: str, max_len: int = 80) -> str:
    """Remove path-unsafe characters, limit length. Returns empty string if result is empty."""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r'[<>:"/\\|?*]', '_', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(' ', 1)[0]
    return s

def apply_template(template: str, metadata: Dict) -> Optional[str]:
    """Replace {field} placeholders with sanitized metadata values.
    Returns the new filename (with .pdf extension) or None if template is unfit."""
    if not template or "{" not in template:
        return None
    result = template
    for key, meta_key in _FIELD_MAP.items():
        placeholder = "{" + key + "}"
        if placeholder not in result:
            continue
        val = metadata.get(meta_key, "")
        if val is None:
            val = ""
        if isinstance(val, list):
            val = val[0] if val else ""
        val = _sanitize(str(val))
        if val:
            result = result.replace(placeholder, val)
        else:
            result = result.replace(placeholder, "")
    # Tidy up: collapse runs and strip noise chars caused by empty fields
    result = re.sub(r'_+', '_', result)
    result = re.sub(r'[_\s\-]+\.pdf$', '.pdf', result)
    result = re.sub(r'^[_\s\-]+', '', result)
    result = re.sub(r'[_\s\-,.()|;:]+$', '', result)
    result = result.strip()
    if not result or result == '.pdf':
        return None
    if not result.lower().endswith('.pdf'):
        result += '.pdf'
    return result
