# ==== bookmark_integrated.py ====
# 职责：整合书葵网和晴天软件的PDF书签获取功能
# 入口函数：get_bookmark_integrated(), fetch_from_shukui(), fetch_from_qingtian()
# 依赖：bookmarkget (书葵网), bookmark_parser (层级推断), requests, pywinauto
# 输出文件：D:\pdf\pdf_add_bookmark_semi.v0.60\bookmark_integrated.py

import os
import re
import sys
import logging
import argparse
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 书签数据结构 ──

@dataclass
class BookmarkItem:
    title: str
    page: int
    level: int = 1
    children: List['BookmarkItem'] = field(default_factory=list)

    def __repr__(self):
        indent = "  " * (self.level - 1)
        return f"{indent}L{self.level} | {self.title} -> p.{self.page}"


# ── 书葵网获取 ──

def fetch_from_shukui(isbn: str) -> Optional[str]:
    """
    从书葵网获取书签原始文本。
    返回: "title\tpage" 格式的多行文本，失败返回 None。
    """
    from addbookmark.bookmarkget import _get_bookmark_sync
    if not isbn:
        return None
    logger.info(f"[书葵网] 尝试 ISBN: {isbn}")
    result = _get_bookmark_sync(isbn)
    if result:
        logger.info(f"[书葵网] 成功获取 {len(result)} 字符")
    else:
        logger.info("[书葵网] 未找到书签")
    return result


def parse_shukui_bookmark(text: str) -> List[BookmarkItem]:
    """将书葵网扁平书签解析为层级列表（中文命名规则推断）。"""
    from addbookmark.bookmark_parser import parse_bookmark_hierarchy
    flat = parse_bookmark_hierarchy(text)
    return [BookmarkItem(title=t, page=p, level=l) for t, p, l in flat]


# ── 晴天软件获取 ──

def _find_qingtian_exe() -> Optional[str]:
    """查找晴天软件 exe 路径。"""
    candidates = [
        r"D:\pdf\pdf_add_bookmark_semi.v0.60\书签获取小工具2015.05.05【晴天软件】.exe",
        os.path.join(os.path.dirname(__file__), "书签获取小工具2015.05.05【晴天软件】.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "书签获取小工具2015.05.05【晴天软件】.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def extract_ssid_from_filename(pdf_path: str) -> Optional[str]:
    """从 PDF 文件名中提取 8 位 SSID。"""
    basename = os.path.basename(pdf_path)
    matches = re.findall(r'\d{8}', basename)
    if matches:
        return matches[0]
    return None


def fetch_from_qingtian(ssid: str, timeout: int = 30) -> Optional[str]:
    """
    通过晴天软件获取书签原始文本。
    使用 pywinauto 自动操作 Windows GUI。
    返回: 书签文本，失败返回 None。
    """
    try:
        from pywinauto.application import Application
        from time import sleep
    except ImportError:
        logger.error("[晴天软件] pywinauto 未安装，请运行: pip install pywinauto")
        return None

    exe_path = _find_qingtian_exe()
    if not exe_path:
        logger.error("[晴天软件] 未找到 exe 文件")
        return None

    logger.info(f"[晴天软件] 启动 exe: {exe_path}")
    logger.info(f"[晴天软件] 输入 SSID: {ssid}")

    try:
        app = Application(backend='win32').start(exe_path)
        dlg = app.window(
            title_re='书签获取小工具2015.05.05  【晴天软件】*',
            class_name_re='WTWindow*'
        )
        dlg.set_focus()

        # 输入 SSID
        dlg['Edit2'].set_edit_text(ssid)

        # 等待结果（Edit 控件有内容且不是话痨提示）
        import time
        start = time.time()
        while time.time() - start < timeout:
            text = dlg['Edit'].window_text()
            if text and not text.startswith('【话痨：】'):
                break
            sleep(0.5)
        else:
            logger.warning("[晴天软件] 等待超时")
            dlg.close()
            return None

        text = dlg['Edit'].window_text()
        dlg.close()

        if text.startswith('没有查询到此SS的书签'):
            logger.info("[晴天软件] 未找到书签")
            return None

        logger.info(f"[晴天软件] 成功获取 {len(text)} 字符")
        return text

    except Exception as e:
        logger.error(f"[晴天软件] 获取失败: {e}")
        return None


def parse_qingtian_bookmark(text: str) -> List[BookmarkItem]:
    """
    解析晴天软件的书签文本。
    格式: Tab 缩进表示层级，每行 "标题\t页码" 或带缩进的 "\t标题\t页码"。
    """
    items = []
    for line in text.strip().split('\n'):
        if not line.strip():
            continue

        # 计算缩进层级（前导 Tab 数）
        stripped = line.lstrip('\t')
        indent = len(line) - len(stripped)
        level = indent + 1  # 0个Tab = L1, 1个Tab = L2, ...

        parts = stripped.split('\t')
        if len(parts) < 2:
            continue

        title = parts[0].strip()
        try:
            page = int(parts[1].strip())
        except ValueError:
            continue

        items.append(BookmarkItem(title=title, page=page, level=level))

    return items


# ── 集成获取 ──

def get_bookmark_integrated(
    pdf_path: str = None,
    isbn: str = None,
    ssid: str = None,
) -> Tuple[Optional[str], List[BookmarkItem], str]:
    """
    集成获取书签：优先书葵网，降级晴天软件。

    Args:
        pdf_path: PDF 文件路径（用于提取 SSID）
        isbn: ISBN 号（用于书葵网查询）
        ssid: SSID 号（用于晴天软件查询）

    Returns:
        (原始文本, 书签列表, 来源名称)
        来源名称: "shukui" / "qingtian" / "none"
    """
    # ── 优先级1：书葵网（ISBN）──
    if isbn:
        raw_text = fetch_from_shukui(isbn)
        if raw_text:
            items = parse_shukui_bookmark(raw_text)
            if items:
                logger.info(f"[书葵网] 解析到 {len(items)} 条书签")
                return raw_text, items, "shukui"

    # ── 优先级2：晴天软件（SSID）──
    # 提取 SSID：优先参数，其次从文件名
    target_ssid = ssid
    if not target_ssid and pdf_path:
        target_ssid = extract_ssid_from_filename(pdf_path)
        if target_ssid:
            logger.info(f"[SSID] 从文件名提取: {target_ssid}")

    if target_ssid:
        raw_text = fetch_from_qingtian(target_ssid)
        if raw_text:
            items = parse_qingtian_bookmark(raw_text)
            if items:
                logger.info(f"[晴天软件] 解析到 {len(items)} 条书签")
                return raw_text, items, "qingtian"

    logger.warning("[集成] 两个来源均未获取到书签")
    return None, [], "none"


# ── 输出格式化 ──

def format_bookmark_text(items: List[BookmarkItem], fmt: str = "tab") -> str:
    """
    将书签列表格式化为文本。

    Args:
        items: 书签列表
        fmt: "tab" = Tab缩进（晴天格式），"quickoutline" = QuickOutline格式
    """
    lines = []
    for item in items:
        if fmt == "tab":
            indent = '\t' * (item.level - 1)
            lines.append(f"{indent}{item.title}\t{item.page}")
        elif fmt == "quickoutline":
            indent = '\t' * (item.level - 1)
            lines.append(f"{indent}{item.title}  {item.page}")
    return '\n'.join(lines)


# ── 命令行接口 ──

def main():
    parser = argparse.ArgumentParser(
        description="整合书葵网和晴天软件的PDF书签获取功能"
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        help="PDF 文件路径（从文件名提取 SSID）"
    )
    parser.add_argument(
        "--isbn",
        help="ISBN 号（书葵网查询）"
    )
    parser.add_argument(
        "--ssid",
        help="SSID 号（晴天软件查询）"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["tab", "quickoutline"],
        default="tab",
        help="输出格式 (default: tab)"
    )
    parser.add_argument(
        "--output", "-o",
        help="输出文件路径 (default: stdout)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细日志"
    )

    args = parser.parse_args()

    # 配置日志
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    # 从 PDF 文件名提取 ISBN/SSID
    isbn = args.isbn
    ssid = args.ssid
    pdf_path = args.pdf_path

    if pdf_path and not isbn:
        # 尝试从文件名提取 ISBN（13位或10位数字）
        basename = os.path.basename(pdf_path)
        isbn_match = re.search(r'(\d{10,13})', basename)
        if isbn_match:
            isbn = isbn_match.group(1)
            logger.info(f"[ISBN] 从文件名提取: {isbn}")

    # 获取书签
    raw_text, items, source = get_bookmark_integrated(
        pdf_path=pdf_path,
        isbn=isbn,
        ssid=ssid,
    )

    if not items:
        print("未获取到书签", file=sys.stderr)
        sys.exit(1)

    # 输出
    result = format_bookmark_text(items, fmt=args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"书签已保存至: {args.output} (来源: {source})", file=sys.stderr)
    else:
        print(f"# 来源: {source}", file=sys.stderr)
        print(result)


if __name__ == "__main__":
    main()
