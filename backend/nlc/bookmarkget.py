import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional


async def get_bookmark(book_id: str, nlc_path: str = "") -> Optional[str]:
    return ""


async def parse_bookmark_hierarchy(raw_bookmark: str) -> List[Dict[str, Any]]:
    if not raw_bookmark:
        return []

    levels = []
    lines = raw_bookmark.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = re.match(r'^(\s*)(\d+(?:\.\d+)*)\s+(.+)$', line)
        if match:
            indent = len(match.group(1))
            number = match.group(2)
            title = match.group(3)
            level = number.count(".") + 1
            page = 0
            levels.append({
                "level": level,
                "number": number,
                "title": title,
                "page": page,
                "indent": indent,
                "children": [],
            })

    tree = _build_tree(levels)
    return tree


def _build_tree(items: List[Dict], parent_level: int = 0) -> List[Dict]:
    result = []
    i = 0
    while i < len(items):
        item = items[i]
        if item["level"] <= parent_level:
            break
        children, j = _build_subtree(items, i + 1, item["level"])
        item["children"] = children
        result.append(item)
        i = j
    return result


def _build_subtree(items: List[Dict], start: int, parent_level: int):
    children = []
    i = start
    while i < len(items):
        item = items[i]
        if item["level"] <= parent_level:
            break
        sub_children, j = _build_subtree(items, i + 1, item["level"])
        item["children"] = sub_children
        children.append(item)
        i = j
    return children, i


async def apply_bookmark_to_pdf(pdf_path: str, bookmark: str) -> bool:
    if not os.path.exists(pdf_path):
        return False

    try:
        import fitz

        toc = parse_bookmark_hierarchy(bookmark)
        if not toc:
            return False

        doc = fitz.open(pdf_path)
        pdf_toc = _convert_to_pdf_toc(toc)
        doc.set_toc(pdf_toc)
        doc.save(pdf_path, incremental=True)
        doc.close()
        return True
    except ImportError:
        pass
    except Exception:
        pass

    return False


def _convert_to_pdf_toc(toc_items: List[Dict], level: int = 1) -> List[List]:
    result = []
    for item in toc_items:
        result.append([item["level"], item["title"], item.get("page", 1)])
        if item.get("children"):
            result.extend(_convert_to_pdf_toc(item["children"], item["level"] + 1))
    return result
