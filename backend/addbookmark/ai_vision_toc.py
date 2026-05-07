"""两阶段 TOC 提取：OCR 文本解析 + AI Vision 兜底。

阶段1: 从 OCR 后的 PDF 文字层解析目录（免费）
阶段2: 用 AI Vision 从目录页图片提取（付费，仅在阶段1失败时触发）
"""
import logging
import re
from typing import Tuple

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
