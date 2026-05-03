import asyncio
from typing import Any, Dict, List, Optional

from backend.nlc.nlc_isbn import crawl_isbn
from backend.nlc.bookmarkget import get_bookmark, parse_bookmark_hierarchy
from backend.nlc.formatting import format_ebook
from backend.nlc.headers import HEADERS as NLC_HEADERS


async def search_nlc(title: str, nlc_path: str = "") -> List[Dict[str, Any]]:
    results = []
    try:
        isbn = await crawl_isbn(title, nlc_path)
        if isbn:
            results.append({"title": title, "isbn": isbn, "source": "NLC"})
    except Exception:
        pass
    return results


async def get_nlc_bookmark(book_id: str, nlc_path: str = "") -> Optional[Dict[str, Any]]:
    try:
        raw = await get_bookmark(book_id, nlc_path)
        if raw:
            hierarchy = parse_bookmark_hierarchy(raw)
            return {"raw": raw, "hierarchy": hierarchy}
    except Exception:
        pass
    return None


async def convert_ebook(input_path: str, output_format: str = "pdf", output_dir: str = "") -> Optional[str]:
    return await format_ebook(input_path, output_format, output_dir)
