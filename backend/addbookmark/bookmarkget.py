# ==== bookmarkget.py ====
# 职责：从书葵网 (shukui.net) 获取目录书签，支持 ISBN 搜索和 PDF 目录注入
# 入口函数：get_bookmark(), apply_bookmark_to_pdf()
# 依赖：headers (get_shukui_headers), requests, BeautifulSoup

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from addbookmark.headers import get_shukui_headers

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


# NOTE: parse_bookmark_hierarchy() below is DEPRECATED.
# Use addbookmark.bookmark_parser.parse_bookmark_hierarchy() instead.
# This old version only handles numbered patterns (1.1.1), not Chinese naming conventions.
async def parse_bookmark_hierarchy(raw_bookmark: str) -> List[Dict[str, Any]]:
    """[DEPRECATED] 将扁平的书签文本解析为层级树。请使用 addbookmark.bookmark_parser.parse_bookmark_hierarchy()。"""
    from addbookmark.bookmark_parser import parse_bookmark_hierarchy as _parse
    flat = _parse(raw_bookmark)
    # Convert to old dict format for backward compatibility
    levels = []
    for title, page, level in flat:
        levels.append({
            "level": level,
            "number": "",
            "title": title,
            "page": page,
            "indent": 0,
            "children": [],
        })
    return levels


async def apply_bookmark_to_pdf(pdf_path: str, bookmark: str, python_cmd: str = "") -> bool:
    """将书葵网书签注入 PDF（使用新的 bookmark_injector 模块）"""
    from addbookmark.bookmark_injector import inject_bookmarks
    if not os.path.exists(pdf_path):
        return False
    try:
        inject_bookmarks(pdf_path, bookmark, pdf_path, offset=0)
        return True
    except Exception as e:
        logger.warning(f"apply_bookmark_to_pdf error: {e}")
        return False
