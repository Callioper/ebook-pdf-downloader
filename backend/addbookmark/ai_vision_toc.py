"""两阶段 TOC 提取：OCR 文本解析 + AI Vision 兜底。

阶段1: 从 OCR 后的 PDF 文字层解析目录（免费）
阶段2: 用 AI Vision 从目录页图片提取（付费，仅在阶段1失败时触发）
"""
import base64
import logging
import os
import re
from typing import List, Optional, Tuple

import httpx

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

    cn_keywords = ['目录', '目 录', '目  录']
    en_keywords = ['CONTENTS', 'Contents', 'Table of Contents']
    all_keywords = cn_keywords + en_keywords
    chapter_pattern = re.compile(r'第[一二三四五六七八九十百千\d]+[章节篇回卷]')
    section_pattern = re.compile(r'^\d+(\.\d+)*\s+\S', re.MULTILINE)

    # 第一遍：找目录头（中文关键词需 CJK 质量检查，英文关键词直接通过）
    toc_start = -1
    for i in range(total):
        text = doc[i].get_text()
        for kw in all_keywords:
            if kw in text:
                is_cn = kw in cn_keywords
                if is_cn and _cjk_ratio(text) < 0.3:
                    logger.debug(f"Page {i}: found '{kw}' but CJK ratio {_cjk_ratio(text):.2f} < 0.3, skipping")
                    continue
                toc_start = i
                break
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
        'xvi': 16, 'xvii': 17, 'xviii': 18, 'xix': 19, 'xx': 20,
        'xxi': 21, 'xxii': 22, 'xxiii': 23, 'xxiv': 24, 'xxv': 25,
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
    # 跳过 markdown 分隔行和表头
    if '---' in line or '章节' in line or '标题' in line:
        return None, None

    # 格式1: tab 分隔 "title\tpage"
    if '\t' in line:
        parts = line.split('\t', 1)
        title = parts[0].strip().lstrip('- ').strip()
        page = _parse_page_number(parts[1])
        if title and page is not None:
            title = _clean_title(title)
            return title, page

    # 格式2: 管道分隔 "title | subtitle | page"
    if '|' in line:
        pipe_parts = [p.strip() for p in line.split('|')]
        pipe_parts = [p for p in pipe_parts if p]
        if len(pipe_parts) >= 2:
            page = _parse_page_number(pipe_parts[-1])
            if page is not None:
                title = pipe_parts[0].strip()
                title = _clean_title(title)
                if title:
                    return title, page

    # 格式3: 点线引导 "- title ..... page" 或 "title ..... page"
    m = re.match(r'^[-*]?\s*(.+?)\s*[.…·]{2,}\s*(\S+)\s*$', line)
    if m:
        title = _clean_title(m.group(1).strip())
        page = _parse_page_number(m.group(2))
        if title and page is not None:
            return title, page

    # 格式4: 空格分隔，最后是数字
    m = re.match(r'^(.+?)\s+(\d+)\s*$', line)
    if m:
        title = _clean_title(m.group(1).strip().lstrip('- ').strip())
        page = _parse_page_number(m.group(2))
        if title and page is not None and page > 0:
            return title, page

    return None, None


def _clean_title(title: str) -> str:
    """清理标题：去除 markdown 标记和英文翻译。"""
    title = re.sub(r'^#+\s*', '', title)
    title = re.split(r'\s*\|\s*[A-Za-z]', title)[0]
    return title.strip()


def _preprocess_toc_text(text: str) -> str:
    """预处理目录文本：合并 OCR 跨行分割的内容。

    处理三种模式：
    1. 标题行 + 点线行 + 页码行 → 合并为一行
       "监禁制度的创立" + "….........…......…" + "14"
       → "监禁制度的创立….........…......…14"

    2. 章号行 + 章标题行 → 合并
       "第一章" + "人类学圈环一一...诞生" + "．．．．" + "1"
       → "第一章 人类学圈环一一...诞生．．．．1"

    3. 节号行 + 节标题行 → 合并
       "2." + "理性、疯狂、疾病——《古典时代疯狂史》" + "…… 11"
       → "2. 理性、疯狂、疾病——《古典时代疯狂史》…… 11"
    """
    lines = text.strip().split('\n')

    # 第一遍：合并纯点线行和页码行
    pass1 = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # 当前行是纯点线 → 合并到前一行
        if re.match(r'^[.…·•\s~\-—]{3,}$', line):
            if pass1:
                pass1[-1] = pass1[-1].rstrip() + line
            i += 1
            continue

        # 下一行是纯点线，再下一行是数字 → 合并三行
        if i + 2 < len(lines):
            next1 = lines[i + 1].strip()
            next2 = lines[i + 2].strip()
            if re.match(r'^[.…·•\s~\-—]{3,}$', next1) and re.match(r'^\d+$', next2):
                pass1.append(line + next1 + next2)
                i += 3
                continue

        # 当前行以点线结尾，下一行是数字 → 合并
        if i + 1 < len(lines):
            next1 = lines[i + 1].strip()
            if re.search(r'[.…·]{2,}\s*$', line) and re.match(r'^\d+$', next1):
                pass1.append(line + next1)
                i += 2
                continue

        pass1.append(line)
        i += 1

    # 第二遍：合并章/节号行和标题行
    pass2 = []
    i = 0
    while i < len(pass1):
        line = pass1[i].strip()
        if not line:
            i += 1
            continue

        # 当前行是章号（如 "第一章"）→ 下一行必然是标题
        if re.match(r'^第[一二三四五六七八九十百千\d]+[章节篇回卷]$', line):
            if i + 1 < len(pass1):
                next_line = pass1[i + 1].strip()
                pass2.append(line + " " + next_line)
                i += 2
                continue

        # 当前行是节号（如 "2."）→ 下一行必然是标题
        if re.match(r'^\d+[.．]\s*$', line):
            if i + 1 < len(pass1):
                next_line = pass1[i + 1].strip()
                pass2.append(line + " " + next_line)
                i += 2
                continue

        pass2.append(line)
        i += 1

    return '\n'.join(pass2)


def extract_toc_from_text(text: str) -> List[Tuple[str, int]]:
    """从文字中解析目录条目。

    策略：先定位章节标题作为锚点，再在章节内解析子条目。
    章节标题用其第一个子条目的页码作为自己的页码。
    """
    if not text or len(text.strip()) < 5:
        return []
    text = _preprocess_toc_text(text)
    lines = text.strip().split('\n')

    # 第一遍：标记哪些行是章节标题
    chapter_indices: List[int] = []
    for i, line in enumerate(lines):
        line = line.strip()
        # 匹配 "第X章"、"第X篇"、"第X部"（允许后面无空格直接跟标题）
        if re.match(r'^第[一二三四五六七八九十百千\d]+[章节篇回卷部]', line):
            chapter_indices.append(i)

    # 第二遍：逐行解析，收集 (title, page, is_chapter)
    raw: List[Tuple[str, Optional[int], bool]] = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line == '目录':
            continue
        is_chapter = i in chapter_indices

        title, page = _parse_toc_line(line)
        if title:
            # 过滤纯点线标题
            clean = re.sub(r'[.…·~•\s\-—_]', '', title)
            if len(clean) >= 2:
                raw.append((title, page, is_chapter))
        elif is_chapter:
            # 章节标题行没有页码 → 记录，页码待回填
            # 标题就是整行（去掉章号后的部分）
            m = re.match(r'^(第[一二三四五六七八九十百千\d]+[章节篇回卷]\s*.+)', line)
            if m:
                raw.append((m.group(1).strip(), None, True))

    # 第三遍：回填章标题的页码（用该章节第一个子条目的页码）
    entries: List[Tuple[str, int]] = []
    pending_chapter: Optional[str] = None
    for title, page, is_chapter in raw:
        if is_chapter:
            if page is not None:
                entries.append((title, page))
                pending_chapter = None
            else:
                pending_chapter = title
        else:
            if pending_chapter and page is not None:
                entries.append((pending_chapter, page))
                pending_chapter = None
            if page is not None:
                entries.append((title, page))

    # 如果还有未回填的章标题（没有子条目），跳过
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


def build_vision_prompt() -> str:
    """多语言智能目录书签生成提示词 — 返回层级缩进的目录文本。"""
    return r"""你是一位资深的多语言文档结构分析专家。请从提供的目录页图片中提取完整目录内容。

## 输出格式（严格执行）
每个条目一行，格式: [层级缩进][标题] [页数]
- 层级0（章）: 无缩进
- 层级1（节）: 1个制表符缩进
- 层级2（条）: 2个制表符缩进
- 层级3（项）: 3个制表符缩进

## 层级判断规则
- 0级: 第[一二三四五六七八九十百千\d]+章、第X部、第X篇、Chapter N、Part N
- 1级: 第X节、\d+\.\d+、Section N、[A-Z]\.
- 2级: [一二三四五]、\d+\.\d+\.\d+、[a-z]\.
- 3级: （[一二三四五]）、\(\d+\)、•|◦|▪

## 页数提取
行尾的数字即为页数。若某行无页数，继承上一条的页数。
中文页码（如"第五页""第123页"）转换为数字。
罗马数字（i, ii, iii, iv...）保持不变。

## 输出示例
```
前言
第1章 绪论 1
	1.1 研究背景 3
		一、问题提出 3
		二、研究意义 5
	1.2 研究现状 8
		一、国外研究现状 8
		二、国内研究现状 10
第2章 理论基础 15
	2.1 基本概念 15
	2.2 理论框架 18
结论 200
参考文献 205
```

## 关键要求
1. 只输出目录内容，不添加任何解释
2. 必须准确识别多级层次结构
3. 页数必须准确提取
4. 忽略非目录内容（页码装饰、页眉页脚等）
5. 中文和英文混合处理，保持原语言文字
"""


def parse_tocify_response(response: str) -> str:
    """Parse Vision LLM output into title<tab>page<tab>level format for bookmark injection.

    Level is preserved from the AI's tab-indentation output:
    0 = chapter (no indent), 1 = section (1 tab), 2+ = subsection.
    """
    import re
    lines = []
    last_page = 1

    # Extract from code block if wrapped in ```
    m = re.search(r'```(.*?)```', response, re.DOTALL)
    text = m.group(1).strip() if m else response.strip()

    for line in text.split('\n'):
        line = line.strip('\r')
        if not line.strip():
            continue

        # Count leading tabs for hierarchy
        tabs = 0
        while line.startswith('\t'):
            tabs += 1
            line = line[1:]
        title = line.strip()

        # Extract page number from end of line
        pm = re.search(r'\s+(\d{1,5})\s*$', title)
        if pm:
            page = int(pm.group(1))
            title = title[:pm.start()].strip()
            last_page = page
        else:
            # Check for Roman numerals
            pm2 = re.search(r'\s+([ivxlcdm]{1,5})\s*$', title, re.I)
            if pm2:
                rm = pm2.group(1)
                title = title[:pm2.start()].strip()
                page = rm
            else:
                page = str(last_page)

        lines.append(f"{title}\t{page}\t{tabs}")

    return '\n'.join(lines)


def parse_vision_response(
    response: str,
) -> Tuple[List[Tuple[str, int]], str, Optional[Tuple[int, int]]]:
    """解析 Vision LLM 响应。

    支持两种格式：
    1. Tab 分隔：标题\\t页码
    2. 层级格式：带缩进的章节列表（页码在行尾或子节点行尾）

    Returns:
        (entries, status, next_page_range)
        status: "TOC_COMPLETE" | "TOC_CONTINUES" | "NO_TOC"
    """
    if not response:
        return [], "NO_TOC", None

    response = response.strip()

    if "NO_TOC" in response.upper():
        return [], "NO_TOC", None

    status = "TOC_COMPLETE"
    next_range = None
    m = re.search(r'TOC_CONTINUES:\s*(\d+)\s*-\s*(\d+)', response)
    if m:
        status = "TOC_CONTINUES"
        next_range = (int(m.group(1)), int(m.group(2)))

    # 先尝试 Tab 分隔格式
    entries = _parse_tab_entries(response)
    if len(entries) >= 3:
        return entries, status, next_range

    # 回退：层级格式解析
    entries = _parse_hierarchical_entries(response)
    return entries, status, next_range


def _parse_tab_entries(response: str) -> List[Tuple[str, int]]:
    """解析 Tab 分隔格式的条目。"""
    lines = response.strip().split('\n')
    entries: List[Tuple[str, int]] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('TOC_') or line == 'NO_TOC':
            continue
        if line in ('目录', '目  录', '目 录', 'Table of Contents', 'Contents'):
            continue
        title, page = _parse_toc_line(line)
        if title and page is not None:
            entries.append((title, page))
    return entries


def _parse_hierarchical_entries(response: str) -> List[Tuple[str, int]]:
    """解析层级格式的目录条目。

    支持：
    1. Tab 缩进格式：\t标题\t页码
    2. Markdown 表格格式
    3. 纯文本层级格式
    """
    # 先尝试 Markdown 表格
    entries = _parse_markdown_table(response)
    if entries:
        return entries

    # Tab 缩进格式
    entries = _parse_indented_entries(response)
    if len(entries) >= 3:
        return entries

    # 回退：逐行解析
    lines = response.strip().split('\n')
    raw_entries: List[Tuple[str, Optional[int]]] = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith('TOC_') or line == 'NO_TOC':
            continue
        if len(line) > 60 and not re.search(r'[.…·]{2,}|\t', line):
            continue

        title, page = _parse_toc_line(line)
        if title:
            raw_entries.append((title, page))
            continue

        clean = line.lstrip('·•- \t').strip()
        if clean and len(clean) >= 2:
            if re.search(r'第[一二三四五六七八九十百千\d]+[章节篇回卷]', clean) or \
               re.match(r'^\d+(\.\d+)*\s+', clean) or \
               re.search(r'[一二三四五六七八九十]+、', clean):
                raw_entries.append((clean, None))

    entries_out: List[Tuple[str, int]] = []
    pending: List[str] = []
    for title, page in raw_entries:
        if page is not None:
            for t in pending:
                entries_out.append((t, page))
            pending.clear()
            entries_out.append((title, page))
        else:
            pending.append(title)

    return entries_out


def _parse_indented_entries(response: str) -> List[Tuple[str, int]]:
    """解析 Tab 缩进格式的层级目录条目。

    格式：
    第一章 标题\t1
    \t第一节 子标题\t3
    \t\t一、小节\t5

    也支持点线格式：
    第一章 标题 ······ 1
    \t1. 子标题 ······ 3
    """
    entries: List[Tuple[str, int]] = []

    for line in response.strip().split('\n'):
        if not line.strip() or line.strip().startswith('TOC_') or line.strip() == 'NO_TOC':
            continue
        if line.strip().startswith('|') and '|' in line.strip()[1:]:
            continue

        # 预处理：把点线 ······ 替换为 \t 便于解析
        content = line.strip()
        content = re.sub(r'\s*[·.…]{3,}\s*', '\t', content)

        # 尝试 "标题\t页码" 格式
        if '\t' in content:
            parts = content.rsplit('\t', 1)
            if len(parts) == 2:
                title = parts[0].strip()
                page = _parse_page_number(parts[1])
                if title and page is not None:
                    # 清理标题中的多余点线
                    title = re.sub(r'[.…·]{2,}', '', title).strip()
                    if title:
                        entries.append((title, page))
                        continue

        # 尝试 "标题 页码" 格式（最后是数字）
        m = re.match(r'^(.+?)\s+(\d+)\s*$', content)
        if m:
            title = m.group(1).strip()
            page = _parse_page_number(m.group(2))
            if title and page is not None and page > 0:
                title = re.sub(r'[.…·]{2,}', '', title).strip()
                if title:
                    entries.append((title, page))

    return entries


def _parse_markdown_table(response: str) -> List[Tuple[str, int]]:
    """解析 Markdown 表格格式的目录。

    格式：
    | 第一章 | 概论 | 1 |
    |   | 背景 | 3 |
    | 第二章 | 基础 | 15 |
    """
    entries: List[Tuple[str, int]] = []
    current_chapter = ""

    for line in response.strip().split('\n'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        if '---' in line or '章节' in line or '标题' in line:
            continue

        # 保留空 cell，不去重
        cells = [c.strip() for c in line.split('|')]
        # 去掉首尾的空字符串（| 分隔产生的）
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]

        if len(cells) < 2:
            continue

        # 最后一个 cell 是页码
        page_str = cells[-1].strip()
        page = _parse_page_number(page_str)
        if page is None:
            continue

        # 前面的 cell 是标题部分
        title_parts = [c for c in cells[:-1] if c]

        if not title_parts:
            continue

        # 判断是否是新章节（第一个非空 cell 包含"第X章"）
        first = title_parts[0]
        if re.search(r'第[一二三四五六七八九十百千\d]+[章节篇回卷]', first):
            current_chapter = first
            if len(title_parts) > 1:
                title = f"{first} {title_parts[1]}"
            else:
                title = first
        else:
            # 子标题：加上当前章节名
            subtitle = ' '.join(title_parts)
            if current_chapter:
                title = f"{current_chapter} {subtitle}"
            else:
                title = subtitle

        entries.append((title, page))

    return entries


def _resolve_api_key(api_key: str) -> str:
    """解析 API Key，支持 {env:VAR_NAME} 语法读取环境变量。"""
    if api_key.startswith("{env:") and api_key.endswith("}"):
        var_name = api_key[5:-1]
        return os.environ.get(var_name, "")
    return api_key


async def call_vision_llm(
    images: List[str],
    prompt: str,
    endpoint: str,
    model: str,
    api_key: str = "",
    timeout: int = 120,
    provider: str = "openai_compatible",
) -> str:
    """调用 Vision LLM API。"""
    if not endpoint:
        raise ValueError("AI Vision: endpoint is required")
    if not model:
        raise ValueError("AI Vision: model is required")

    api_key = _resolve_api_key(api_key)

    # Alias mapping
    if provider in ("minimax_openai", "zhipu", "ollama", "lmstudio", "doubao"):
        provider = "openai_compatible"
    elif provider in ("minimax_anthropic",):
        provider = "anthropic"
    elif provider in ("openai_responses",):
        provider = "responses"

    if provider == "gemini":
        return await _call_gemini(images, prompt, endpoint, model, api_key, timeout)
    elif provider == "anthropic":
        return await _call_minimax(images, prompt, endpoint, model, api_key, timeout)
    elif provider == "azure":
        return await _call_azure(images, prompt, endpoint, model, api_key, timeout)
    elif provider == "responses":
        return await _call_openai_responses(images, prompt, endpoint, model, api_key, timeout)
    elif provider == "custom":
        try:
            return await _call_openai_compatible(images, prompt, endpoint, model, api_key, timeout)
        except Exception:
            return await _call_minimax(images, prompt, endpoint, model, api_key, timeout)
    else:
        return await _call_openai_compatible(images, prompt, endpoint, model, api_key, timeout)


async def _call_azure(
    images: List[str], prompt: str, endpoint: str, model: str,
    api_key: str, timeout: int,
) -> str:
    """Azure OpenAI API (api-version in URL, api-key auth header)."""
    url = (
        f"{endpoint.rstrip('/')}/openai/deployments/{model}"
        f"/chat/completions?api-version=2024-02-15-preview"
    )
    content = [{"type": "text", "text": prompt}]
    for img_b64 in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
    payload = {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096, "temperature": 0.1,
    }
    headers = {"Content-Type": "application/json", "api-key": api_key}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_openai_responses(
    images: List[str], prompt: str, endpoint: str, model: str,
    api_key: str, timeout: int,
) -> str:
    """OpenAI Responses API (/v1/responses, newer than chat/completions)."""
    url = f"{endpoint.rstrip('/')}/responses"
    content = [{"type": "input_text", "text": prompt}]
    for img_b64 in images:
        content.append({"type": "input_image", "image_url": f"data:image/png;base64,{img_b64}"})
    payload = {"model": model, "input": content}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        for output in data.get("output", []):
            if output.get("type") == "message":
                for item in output.get("content", []):
                    if item.get("type") == "output_text":
                        return item["text"]
        return ""


async def _call_openai_compatible(
    images: List[str], prompt: str, endpoint: str, model: str,
    api_key: str, timeout: int,
) -> str:
    url = f"{endpoint.rstrip('/')}/chat/completions"
    content = [{"type": "text", "text": prompt}]
    for img_b64 in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
    payload = {"model": model, "messages": [{"role": "user", "content": content}],
               "max_tokens": 4096, "temperature": 0.1}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_gemini(
    images: List[str], prompt: str, endpoint: str, model: str,
    api_key: str, timeout: int,
) -> str:
    url = f"{endpoint.rstrip('/')}/models/{model}:generateContent?key={api_key}"
    parts = [{"text": prompt}]
    for img_b64 in images:
        parts.append({"inline_data": {"mime_type": "image/png", "data": img_b64}})
    payload = {"contents": [{"parts": parts}]}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _call_minimax(
    images: List[str], prompt: str, endpoint: str, model: str,
    api_key: str, timeout: int,
) -> str:
    """Call MiniMax M2.7 Vision API (Anthropic Messages format)."""
    url = f"{endpoint.rstrip('/')}/v1/messages"

    content = []
    for img_b64 in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            },
        })
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


def extract_toc_images(
    pdf_path: str,
    page_start: int = 0,
    page_end: int = -1,
    max_pages: int = 10,
    dpi: int = 150,
) -> List[str]:
    """提取 PDF 指定页码范围为 base64 PNG 图片。"""
    import fitz

    doc = fitz.open(pdf_path)
    total = len(doc)
    if page_end < 0:
        page_end = total - 1
    page_end = min(page_end, total - 1)
    page_start = max(0, page_start)
    if page_end - page_start + 1 > max_pages:
        page_end = page_start + max_pages - 1

    images = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i in range(page_start, page_end + 1):
        pix = doc[i].get_pixmap(matrix=mat)
        images.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    doc.close()
    return images


def _cross_validate_entries(
    vision_entries: List[Tuple[str, int]],
    ocr_text: str,
    min_match_ratio: float = 0.3,
) -> List[Tuple[str, int]]:
    """交叉验证：Vision 返回的标题是否在 OCR 文字中出现过。"""
    if not ocr_text or not vision_entries:
        return vision_entries

    def _normalize(s: str) -> str:
        return re.sub(r'[\s\.\-—·…\t]', '', s)

    ocr_clean = _normalize(ocr_text)
    validated = []
    matched = 0

    for title, page in vision_entries:
        title_clean = _normalize(title)
        if len(title_clean) >= 4:
            snippet = title_clean[:4]
            if snippet in ocr_clean:
                validated.append((title, page))
                matched += 1
            else:
                logger.debug(f"幻觉检测: '{title[:20]}' 未在 OCR 文字中找到，丢弃")
        else:
            validated.append((title, page))

    match_ratio = matched / len(vision_entries) if vision_entries else 0
    if match_ratio < min_match_ratio and len(vision_entries) >= 3:
        # 匹配率过低说明 OCR 文字可能不可用（乱码），保留原条目
        logger.debug(f"幻觉检测: 匹配率 {match_ratio:.2f} < {min_match_ratio}，跳过交叉验证")
        return vision_entries

    return validated


async def extract_toc_from_vision(
    pdf_path: str,
    config: dict,
    toc_page_hint: Tuple[int, int] = (-1, -1),
    ocr_text_for_validation: str = "",
    max_rounds: int = 3,
    dpi: int = 150,
) -> str:
    """阶段2: 用 AI Vision 从 PDF 图片提取目录（付费 API）。"""
    endpoint = config.get("ai_vision_endpoint", "")
    model = config.get("ai_vision_model", "")
    api_key = config.get("ai_vision_api_key", "")
    provider = config.get("ai_vision_provider", "openai_compatible")
    batch_size = config.get("ai_vision_max_pages", 3)

    if not endpoint or not model:
        logger.info("AI Vision: 未配置 endpoint/model")
        return ""

    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    all_entries: List[Tuple[str, int]] = []
    seen_titles: set[str] = set()

    if toc_page_hint[0] >= 0:
        # Phase 1 已定位目录页 → 分批精细提取
        page_start = toc_page_hint[0]
        page_end = toc_page_hint[1]
        logger.info(f"AI Vision: 使用 OCR 定位的目录页范围 {page_start}-{page_end}")

        current_page = page_start
        round_num = 0
        while current_page <= page_end and round_num < max_rounds:
            batch_end = min(current_page + batch_size - 1, page_end)
            images = extract_toc_images(
                pdf_path, page_start=current_page, page_end=batch_end,
                max_pages=batch_size, dpi=dpi,
            )
            if not images:
                break

            round_num += 1
            logger.info(f"AI Vision: 第{round_num}轮，页 {current_page}-{batch_end}，{len(images)} 张图")

            prompt = build_vision_prompt()
            try:
                response = await call_vision_llm(
                    images=images, prompt=prompt,
                    endpoint=endpoint, model=model,
                    api_key=api_key, provider=provider,
                )
            except Exception as e:
                logger.warning(f"AI Vision: 第{round_num}轮失败: {e}")
                break

            parsed_entries, status, next_range = parse_vision_response(response)
            logger.info(f"AI Vision: 第{round_num}轮提取 {len(parsed_entries)} 条 (status={status})")

            for title, page in parsed_entries:
                norm = re.sub(r'\s+', '', title).lower()
                if norm not in seen_titles:
                    seen_titles.add(norm)
                    all_entries.append((title, page))

            current_page = batch_end + 1
    else:
        # Phase 1 未定位 → 扫描多个页码范围找目录
        logger.info("AI Vision: OCR 未定位目录，扫描多页范围")
        for scan_start in [0, 5, 10, 15]:
            if scan_start >= total_pages:
                break
            scan_end = min(scan_start + 4, total_pages - 1)
            images = extract_toc_images(
                pdf_path, page_start=scan_start, page_end=scan_end,
                max_pages=5, dpi=dpi,
            )
            if not images:
                continue

            prompt = build_vision_prompt()
            try:
                response = await call_vision_llm(
                    images=images, prompt=prompt,
                    endpoint=endpoint, model=model,
                    api_key=api_key, provider=provider,
                )
            except Exception as e:
                logger.warning(f"AI Vision: 扫描页{scan_start}-{scan_end}失败: {e}")
                continue

            parsed_entries, status, next_range = parse_vision_response(response)
            logger.info(f"AI Vision: 扫描页{scan_start}-{scan_end}提取 {len(parsed_entries)} 条 (status={status})")

            for title, page in parsed_entries:
                norm = re.sub(r'\s+', '', title).lower()
                if norm not in seen_titles:
                    seen_titles.add(norm)
                    all_entries.append((title, page))

            # 找到目录后继续扫描后续页
            if len(all_entries) >= 3:
                # 继续从这个范围往后扫描
                for next_start in [scan_end + 1, scan_end + 4]:
                    if next_start >= total_pages:
                        break
                    next_end = min(next_start + 4, total_pages - 1)
                    images = extract_toc_images(
                        pdf_path, page_start=next_start, page_end=next_end,
                        max_pages=5, dpi=dpi,
                    )
                    if not images:
                        continue

                    prompt = build_vision_prompt()
                    try:
                        response = await call_vision_llm(
                            images=images, prompt=prompt,
                            endpoint=endpoint, model=model,
                            api_key=api_key, provider=provider,
                        )
                    except Exception as e:
                        logger.warning(f"AI Vision: 续扫页{next_start}-{next_end}失败: {e}")
                        continue

                    more_parsed, more_status, more_range = parse_vision_response(response)
                    logger.info(f"AI Vision: 续扫页{next_start}-{next_end}提取 {len(more_parsed)} 条 (status={more_status})")
                    for title, page in more_parsed:
                        norm = re.sub(r'\s+', '', title).lower()
                        if norm not in seen_titles:
                            seen_titles.add(norm)
                            all_entries.append((title, page))
                break

    if not all_entries:
        logger.info("AI Vision: 未提取到任何目录条目")
        return ""

    if ocr_text_for_validation:
        all_entries = _cross_validate_entries(all_entries, ocr_text_for_validation)
        if not all_entries:
            logger.info("AI Vision: 交叉验证后无有效条目（可能全是幻觉）")
            return ""

    if not validate_entries(all_entries, total_pages=total_pages, min_entries=3):
        logger.info("AI Vision: 质量检查失败")
        return ""

    bookmark_text = format_entries_to_bookmark(all_entries)
    logger.info(f"AI Vision: 共提取 {len(all_entries)} 条目录（已验证）")
    return bookmark_text


async def generate_toc(
    pdf_path: str,
    config: dict,
) -> Tuple[str, str]:
    """AI Vision TOC 提取——直接盲扫前20页，不依赖 find_toc_pages 自动定位。"""
    ai_vision_enabled = config.get("ai_vision_enabled", True)
    if not ai_vision_enabled:
        logger.info("TOC 提取: AI Vision 已禁用")
        return ("", "")

    ai_endpoint = config.get("ai_vision_endpoint", "")
    ai_model = config.get("ai_vision_model", "")
    ai_api_key = config.get("ai_vision_api_key", "")
    ai_provider = config.get("ai_vision_provider", "openai_compatible")

    if ai_provider == "doubao":
        ai_model = config.get("ai_vision_endpoint_id", "") or ai_model
        ai_api_key = config.get("ai_vision_doubao_key", "") or ai_api_key
    elif ai_provider == "zhipu":
        ai_api_key = config.get("ai_vision_zhipu_key", "") or ai_api_key

    if not ai_endpoint or not ai_model:
        logger.info("TOC 提取: AI Vision 未配置")
        return ("", "")

    logger.info("TOC 提取: AI Vision 盲扫前20页")
    # Pass resolved config values so extract_toc_from_vision uses correct model/key
    resolved_config = dict(config)
    resolved_config["ai_vision_model"] = ai_model
    resolved_config["ai_vision_api_key"] = ai_api_key
    bookmark = await extract_toc_from_vision(
        pdf_path, resolved_config,
        toc_page_hint=(-1, -1),
        ocr_text_for_validation="",
    )

    if bookmark:
        logger.info("TOC 提取: 成功")
        return (bookmark, "ai_vision")

    logger.info("TOC 提取: 未找到目录")
    return ("", "")
