# ==== bookmarkget.py ====
# 职责：从书葵网 (shukui.net) 获取目录书签，支持 ISBN 搜索和 PDF 目录注入
# 入口函数：get_bookmark(), apply_bookmark_to_pdf()
# 依赖：headers (get_shukui_headers), requests, BeautifulSoup

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from backend.nlc.headers import get_shukui_headers

logger = logging.getLogger(__name__)


async def get_bookmark(book_id: str, nlc_path: str = "") -> Optional[str]:
    """
    从书葵网获取目录书签。
    注意：book_id 参数虽然名称是 book_id，但实际需要 ISBN。
    这是为了兼容 pipeline Step 6 的调用（传入 report 中的 ISBN）。
    如果是13位ISBN且未找到，自动截取后10位再试。
    """
    isbn = book_id  # book_id 参数实际就是 ISBN
    if not isbn:
        return None

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _get_bookmark_sync, isbn)
    return result


def _get_bookmark_sync(isbn: str) -> Optional[str]:
    """同步方式搜索书葵网获取书签"""
    # 搜索书葵网
    search_url = "https://www.shukui.net/so/search.php"
    params = {'q': isbn}
    headers = get_shukui_headers()

    try:
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.warning(f"shukui.net search returned HTTP {response.status_code}")
            return None

        response.encoding = 'utf-8'
        html = response.text

        # 解析搜索结果，找第一个 cate-item
        soup = BeautifulSoup(html, 'html.parser')
        cate_item = soup.find('div', class_='cate-item')
        if not cate_item:
            # 13位ISBN未找到，尝试后10位
            if len(isbn) == 13:
                isbn_10 = isbn[3:]
                logger.info(f"shukui.net: 13-digit ISBN not found, trying ISBN-10: {isbn_10}")
                return _get_bookmark_sync(isbn_10)
            logger.info(f"shukui.net: no cate-item found for ISBN={isbn}")
            return None

        # 提取详情页链接
        link_tag = cate_item.find('a')
        if not link_tag or not link_tag.get('href'):
            logger.info(f"shukui.net: no detail link in cate-item")
            return None

        relative_link = link_tag['href']
        details_url = f"https://www.shukui.net{relative_link}"
        logger.debug(f"shukui.net: detail page: {details_url}")

        # 请求详情页
        detail_resp = requests.get(details_url, headers=headers, timeout=10)
        if detail_resp.status_code != 200:
            logger.warning(f"shukui.net detail page HTTP {detail_resp.status_code}")
            return None

        detail_resp.encoding = 'utf-8'
        detail_html = detail_resp.text

        # 提取 id="book-contents" 的内容
        detail_soup = BeautifulSoup(detail_html, 'html.parser')
        book_contents = detail_soup.find(id="book-contents")
        if not book_contents:
            logger.info(f"shukui.net: no book-contents found")
            return None

        bookmark_text = book_contents.text.strip()
        if bookmark_text:
            logger.info(f"shukui.net: got bookmark ({len(bookmark_text)} chars)")
            return bookmark_text

        return None

    except requests.Timeout:
        logger.warning("shukui.net: request timed out")
        return None
    except requests.ConnectionError as e:
        logger.warning(f"shukui.net: connection error: {e}")
        return None
    except Exception as e:
        logger.warning(f"shukui.net: error: {e}")
        return None


async def parse_bookmark_hierarchy(raw_bookmark: str) -> List[Dict[str, Any]]:
    """将扁平的书签文本解析为层级树"""
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


async def apply_bookmark_to_pdf(pdf_path: str, bookmark: str, python_cmd: str = "") -> bool:
    """将解析后的书签注入 PDF 文件，支持 exe 环境下通过系统 Python 兜底"""
    if not os.path.exists(pdf_path):
        return False

    # First try: direct import (works in dev/venv)
    try:
        import fitz

        toc = await parse_bookmark_hierarchy(bookmark)
        if not toc:
            return False

        doc = fitz.open(pdf_path)
        pdf_toc = _convert_to_pdf_toc(toc)
        doc.set_toc(pdf_toc)
        doc.save(pdf_path, incremental=True)
        doc.close()
        return True
    except ImportError:
        pass  # fitz not available, try subprocess fallback
    except Exception as e:
        logger.warning(f"apply_bookmark_to_pdf error: {e}")
        return False

    # Fallback: use system Python subprocess (works in frozen exe)
    if not python_cmd:
        return False
    try:
        toc = await parse_bookmark_hierarchy(bookmark)
        if not toc:
            return False
        pdf_toc = _convert_to_pdf_toc(toc)
        import json, subprocess as _sp
        script = (
            "import json,sys;"
            "data=json.loads(sys.stdin.read());"
            "import fitz;"
            "doc=fitz.open(data['p']);"
            "doc.set_toc(data['t']);"
            "doc.save(data['p'], incremental=True);"
            "doc.close();"
            "print('OK')"
        )
        r = _sp.run([python_cmd, "-c", script],
                    input=json.dumps({"p": pdf_path, "t": pdf_toc}),
                    capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip() == "OK":
            return True
        logger.warning(f"apply_bookmark_to_pdf subprocess failed: {r.stderr[:200]}")
    except Exception as e:
        logger.warning(f"apply_bookmark_to_pdf subprocess error: {e}")
    return False


def _convert_to_pdf_toc(toc_items: List[Dict], level: int = 1) -> List[List]:
    result = []
    for item in toc_items:
        result.append([item["level"], item["title"], item.get("page", 1)])
        if item.get("children"):
            result.extend(_convert_to_pdf_toc(item["children"], item["level"] + 1))
    return result
