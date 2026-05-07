"""两阶段 TOC 提取：OCR 文本解析 + AI Vision 兜底。

阶段1: 从 OCR 后的 PDF 文字层解析目录（免费）
阶段2: 用 AI Vision 从目录页图片提取（付费，仅在阶段1失败时触发）
"""
import base64
import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def _cjk_ratio(text: str) -> float:
    """计算文本中 CJK 字符的占比。"""
    if not text:
        return 0.0
    total = sum(1 for c in text if not c.isspace())
    if total == 0:
        return 0.0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'
              or '\u3400' <= c <= '\u4dbf'
              or '\uf900' <= c <= '\ufaff')
    return cjk / total


def _count_page_refs(text: str) -> int:
    """统计文本中的页码引用数量（点线引导/Tab+数字）。"""
    dot_leaders = len(re.findall(r'[.…·]{2,}\s*\S+', text))
    tab_numbers = len(re.findall(r'\t\S+\s*$', text, re.MULTILINE))
    return dot_leaders + tab_numbers


def find_toc_pages(pdf_path: str, scan_limit: int = 30) -> Tuple[int, int]:
    """定位 PDF 中的目录页范围。

    策略：
    1. 找 "目录/目 录/CONTENTS" 关键词所在页 → 验证 CJK 占比 ≥ 30%（排除 OCR 乱码）
    2. 如果没找到关键词头，用 "第X章/第X节" 密度 + 页码引用 联合定位
       （单独的章节关键词不够，必须同时有页码引用，排除章节开头页）
    3. 从 toc_start 往后扫描连续目录页

    Returns:
        (start_page, end_page) 0-indexed，找不到返回 (-1, -1)
    """
    import fitz

    doc = fitz.open(pdf_path)
    total = min(scan_limit, len(doc))

    header_keywords = ['目录', '目 录', '目  录', 'CONTENTS', 'Contents', 'Table of Contents']
    chapter_pattern = re.compile(r'第[一二三四五六七八九十百千\d]+[章节篇回卷]')
    section_pattern = re.compile(r'^\d+(\.\d+)*\s+\S', re.MULTILINE)

    # 第一遍：找目录头（带 CJK 质量检查）
    toc_start = -1
    for i in range(total):
        text = doc[i].get_text()
        for kw in header_keywords:
            if kw in text:
                if _cjk_ratio(text) >= 0.3:
                    toc_start = i
                    break
                else:
                    logger.debug(f"Page {i}: found '{kw}' but CJK ratio {_cjk_ratio(text):.2f} < 0.3, skipping")
        if toc_start >= 0:
            break

    # 第二遍：如果没找到头，用密度 + 页码引用联合定位
    if toc_start < 0:
        for i in range(total):
            text = doc[i].get_text()
            chapter_hits = len(chapter_pattern.findall(text))
            section_hits = len(section_pattern.findall(text))
            page_refs = _count_page_refs(text)
            if chapter_hits + section_hits >= 3 and page_refs >= 2:
                toc_start = i
                break

    if toc_start < 0:
        doc.close()
        return (-1, -1)

    # 第三遍：从 toc_start 往后找目录结束
    toc_end = toc_start
    for i in range(toc_start, total):
        text = doc[i].get_text()
        chapter_hits = len(chapter_pattern.findall(text))
        section_hits = len(section_pattern.findall(text))
        page_refs = _count_page_refs(text)

        if chapter_hits + section_hits >= 2 or page_refs >= 1:
            toc_end = i
        else:
            if i > toc_start:
                break

    doc.close()
    return (toc_start, toc_end)


# ── 中文数字转换 ──

_CN_NUM_MAP = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
    '十': 10, '百': 100, '千': 1000,
}


def _cn_to_int(s: str) -> Optional[int]:
    """中文数字转 int，无法解析返回 None。"""
    s = s.strip()
    if not s:
        return None
    if s in _CN_NUM_MAP:
        return _CN_NUM_MAP[s]
    if s.startswith('十') and len(s) == 2:
        rest = _CN_NUM_MAP.get(s[1])
        if rest is not None:
            return 10 + rest
    if s.endswith('十') and len(s) == 2:
        first = _CN_NUM_MAP.get(s[0])
        if first is not None:
            return first * 10
    if len(s) == 3 and s[1] == '十':
        first = _CN_NUM_MAP.get(s[0])
        last = _CN_NUM_MAP.get(s[2])
        if first is not None and last is not None:
            return first * 10 + last
    return None


def _parse_page_number(s: str) -> Optional[int]:
    """解析页码字符串（阿拉伯数字/中文数字/罗马数字）。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    roman_map = {
        'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
        'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10,
        'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15,
    }
    if s.lower() in roman_map:
        return roman_map[s.lower()]
    cn = _cn_to_int(s)
    if cn is not None:
        return cn
    return None


def _parse_toc_line(line: str) -> Tuple[Optional[str], Optional[int]]:
    """解析单行目录条目 → (title, page)。"""
    line = line.strip()
    if not line or len(line) < 3:
        return None, None
    if line in ('目录', '目  录', '目 录', 'Table of Contents', 'Contents'):
        return None, None

    # 格式1: tab 分隔 "title\tpage"
    if '\t' in line:
        parts = line.split('\t', 1)
        title = parts[0].strip().lstrip('- ').strip()
        page = _parse_page_number(parts[1])
        if title and page is not None:
            return title, page

    # 格式2: 点线引导 "- title ..... page" 或 "title ..... page"
    m = re.match(r'^[-*]?\s*(.+?)\s*[.…·]{2,}\s*(\S+)\s*$', line)
    if m:
        title = m.group(1).strip()
        page = _parse_page_number(m.group(2))
        if title and page is not None:
            return title, page

    # 格式3: 空格分隔，最后是数字
    m = re.match(r'^(.+?)\s+(\d+)\s*$', line)
    if m:
        title = m.group(1).strip().lstrip('- ').strip()
        page = _parse_page_number(m.group(2))
        if title and page is not None and page > 0:
            return title, page

    return None, None


def extract_toc_from_text(text: str) -> List[Tuple[str, int]]:
    """从文字中解析目录条目。"""
    if not text or len(text.strip()) < 5:
        return []
    lines = text.strip().split('\n')
    entries: List[Tuple[str, int]] = []
    for line in lines:
        title, page = _parse_toc_line(line)
        if title and page is not None:
            entries.append((title, page))
    return entries


def validate_entries(
    entries: List[Tuple[str, int]],
    total_pages: int = 0,
    min_entries: int = 3,
    max_non_monotonic_ratio: float = 0.3,
) -> bool:
    """验证提取的目录条目是否合格。

    检查项：
    1. 条目数 ≥ min_entries
    2. 页码 ≤ total_pages * 3（允许不同页码体系）
    3. 页码大体递增（非递增占比 ≤ max_non_monotonic_ratio）

    Returns:
        True = 合格，False = 不合格
    """
    if len(entries) < min_entries:
        logger.info(f"质量检查: 条目数 {len(entries)} < {min_entries}")
        return False

    # 页码范围检查
    if total_pages > 0:
        max_allowed = total_pages * 3
        out_of_range = sum(1 for _, p in entries if p > max_allowed or p <= 0)
        if out_of_range > len(entries) * 0.5:
            logger.info(f"质量检查: {out_of_range}/{len(entries)} 条目页码超范围 (max={max_allowed})")
            return False

    # 页码单调性检查
    if len(entries) >= 3:
        pages = [p for _, p in entries]
        non_monotonic = 0
        for i in range(1, len(pages)):
            if pages[i] < pages[i - 1]:
                if pages[i - 1] - pages[i] > 10:
                    non_monotonic += 1
        ratio = non_monotonic / (len(pages) - 1)
        if ratio > max_non_monotonic_ratio:
            logger.info(f"质量检查: 页码非递增比例 {ratio:.2f} > {max_non_monotonic_ratio}")
            return False

    return True


def format_entries_to_bookmark(entries: List[Tuple[str, int]]) -> str:
    """将 (title, page) 列表转为 tab 分隔的书签文本。"""
    return "\n".join(f"{title}\t{page}" for title, page in entries)


def extract_toc_from_ocr_text(
    pdf_path: str,
    min_entries: int = 3,
    max_scan_pages: int = 30,
) -> Tuple[str, int, int]:
    """阶段1: 从 OCR 文字层提取目录（免费）。

    Returns:
        (bookmark_text, toc_start_page, toc_end_page)
        bookmark_text 为空表示提取/验证失败
        toc_start/end 可能有效（用于阶段2 的页码提示）
    """
    import fitz

    toc_start, toc_end = find_toc_pages(pdf_path, scan_limit=max_scan_pages)
    if toc_start < 0:
        logger.info("OCR TOC: 未找到目录页")
        return ("", -1, -1)

    logger.info(f"OCR TOC: 定位目录页 {toc_start}-{toc_end}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    toc_text_parts = []
    for i in range(toc_start, min(toc_end + 1, total_pages)):
        toc_text_parts.append(doc[i].get_text())
    doc.close()

    toc_text = "\n".join(toc_text_parts)
    entries = extract_toc_from_text(toc_text)

    if not validate_entries(entries, total_pages=total_pages, min_entries=min_entries):
        logger.info(f"OCR TOC: 质量检查失败（{len(entries)} 条目）")
        return ("", toc_start, toc_end)

    bookmark_text = format_entries_to_bookmark(entries)
    logger.info(f"OCR TOC: 成功提取 {len(entries)} 条目录")
    return (bookmark_text, toc_start, toc_end)
