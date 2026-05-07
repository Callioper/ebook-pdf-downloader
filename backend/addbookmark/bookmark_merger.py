"""Smart merge bookmarks from multiple sources into one unified TOC."""
import re
from typing import Optional, List, Tuple


def _normalize_title(title: str) -> str:
    """Normalize title for comparison."""
    return re.sub(r'\s+', '', title.strip()).lower()


def _extract_lines(text: str) -> List[Tuple[str, str]]:
    """Parse tab-separated 'title\tpage' lines. Returns [(title, page), ...]"""
    lines = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 2:
            title = parts[0].strip()
            page = parts[1].strip()
            if title:
                lines.append((title, page))
        elif line:
            lines.append((line, ''))
    return lines


def _extract_titles_only(text: str) -> List[str]:
    """Extract chapter titles from plain text TOC (no page numbers)."""
    titles = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or len(line) < 3:
            continue
        # Skip header lines like "目录", "目  录", etc.
        if line in ('目录', '目  录', '目 录', 'Table of Contents'):
            continue
        # Extract the meaningful part
        clean = re.sub(r'^[\s\.\d\-—·•●○■□▪▫]+', '', line).strip()
        if clean and len(clean) >= 3:
            titles.append(clean)
    return titles


def merge_bookmarks(
    shukui: str = '',
    douban_toc: str = '',
    nlc_toc: str = '',
) -> str:
    """
    Smart merge bookmarks from multiple sources.
    Returns unified 'title\\tpage' format text.

    Priority: Shukui (with pages) > Douban > NLC.
    Deduplicates by title similarity.
    """
    seen_titles = set()
    result_lines = []

    def _add(title: str, page: str = ''):
        norm = _normalize_title(title)
        # Check if similar title already exists
        for existing in seen_titles:
            if norm in existing or existing in norm:
                return
            # 80% character overlap
            common = sum(1 for c in norm if c in existing)
            if common > len(norm) * 0.8 or common > len(existing) * 0.8:
                return
        seen_titles.add(norm)
        if page:
            result_lines.append(f"{title}\t{page}")
        else:
            result_lines.append(title)

    # Source 1: Shukui (best, has page numbers)
    if shukui:
        for title, page in _extract_lines(shukui):
            _add(title, page)

    # Source 2: Douban TOC
    if douban_toc:
        for title in _extract_titles_only(douban_toc):
            _add(title, '')

    # Source 3: NLC TOC
    if nlc_toc:
        for title in _extract_titles_only(nlc_toc):
            _add(title, '')

    return '\n'.join(result_lines)
