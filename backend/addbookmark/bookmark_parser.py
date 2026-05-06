"""Parse flat 书葵网 bookmark text into hierarchical structure."""

import re
from typing import List, Tuple


def detect_bookmark_level(title: str) -> tuple:
    """
    Infer bookmark level from Chinese naming conventions.

    Returns: (level, is_container)
        level: 1-4 (1=top, e.g. Part; 2=Chapter; 3=Section; 4=Subsection)
        is_container: True if this is a container node whose children follow
    """
    title_clean = title.strip()

    # Level 1: 部分/篇/卷 (top-level containers)
    if re.search(r'第[一二三四五六七八九十百千]+部分', title_clean):
        return (1, True)
    if re.search(r'第[一二三四五六七八九十百千]+篇', title_clean):
        return (1, True)
    if re.search(r'^[上下]篇\b', title_clean):
        return (1, True)
    if re.search(r'卷[一二三四五六七八九十]+', title_clean):
        return (1, True)

    # Level 2: 章
    if re.search(r'第[一二三四五六七八九十百千]+章', title_clean):
        return (2, True)
    if re.search(r'^Chapter\s+\d+', title_clean, re.IGNORECASE):
        return (2, True)

    # Level 3: 节
    if re.search(r'第[一二三四五六七八九十百千]+节', title_clean):
        return (3, True)
    if re.search(r'^Section\s+\d+', title_clean, re.IGNORECASE):
        return (3, True)

    # Level 4: numbered subsections
    if re.match(r'^[一二三四五六七八九十]+、', title_clean):
        return (4, False)
    if re.match(r'^（[一二三四五六七八九十]+）', title_clean):
        return (4, False)
    if re.match(r'^\d+(\.\d+)*\s', title_clean):
        return (4, False)
    if re.match(r'^\(\d+\)', title_clean):
        return (4, False)

    # Special prefixes (appendix, references, etc.)
    for kw in ['附录', '参考文献', '参考书目', '索引', '后记',
               '跋', '补遗', '术语表', '名词索引', '人名索引']:
        if title_clean.startswith(kw):
            return (1, False)

    # Unrecognized → default level 2 (chapter-level leaf)
    return (2, False)


def parse_bookmark_hierarchy(bookmark_text: str) -> List[Tuple[str, int, int]]:
    """
    Parse flat 书葵网 bookmark text into hierarchical list.

    Input: 书葵网 raw text ("title\tpage", one entry per line)
    Output: [(title, shukui_page, effective_level), ...]
    """
    if not bookmark_text:
        return []

    lines = bookmark_text.strip().split('\n')
    entries = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        title = parts[0].strip()
        try:
            shukui_page = int(parts[1].strip())
        except ValueError:
            continue
        level, is_container = detect_bookmark_level(title)
        entries.append({
            'title': title,
            'shukui_page': shukui_page,
            'raw_level': level,
            'is_container': is_container,
        })

    if not entries:
        return []

    # Stack-based hierarchy adjustment
    result = []
    stack = []  # container nodes only: {'raw_level': int}

    for entry in entries:
        raw_lv = entry['raw_level']
        is_cont = entry['is_container']

        # Pop: current raw_level >= stack top → pop
        while stack and raw_lv <= stack[-1]['raw_level']:
            stack.pop()

        # Effective level = stack depth + 1
        effective_level = min(len(stack) + 1, 4)

        result.append((entry['title'], entry['shukui_page'], effective_level))

        if is_cont:
            stack.append({'raw_level': raw_lv})

    return result
