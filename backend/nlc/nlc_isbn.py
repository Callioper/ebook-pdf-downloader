# ==== nlc_isbn.py ====
# 职责：从国家图书馆（NLC）爬取ISBN信息
# 入口函数：crawl_isbn()
# 依赖：backend.nlc.headers
# 注意：异步执行，支持标题清洗和多页面查询

import asyncio
import os
import re
from typing import Optional, Dict

import requests
from bs4 import BeautifulSoup

from backend.nlc.headers import HEADERS, NLC_SEARCH_URL


async def crawl_isbn(title: str, nlc_path: str = "") -> Optional[str]:
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _crawl_isbn_sync, title)
        return result
    except Exception:
        return None


async def crawl_metadata(isbn: str) -> Optional[Dict[str, str]]:
    """Fetch author, publisher, year from NLC OPAC by ISBN.
    Returns dict with keys: isbn, author, publisher, year, or None."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _crawl_metadata_sync, isbn)
        return result
    except Exception:
        return None


def _crawl_metadata_sync(isbn: str) -> Optional[Dict[str, str]]:
    """Search NLC OPAC by ISBN, navigate to detail page, extract MARC fields."""
    if not isbn or not isbn.strip():
        return None
    try:
        clean_isbn = re.sub(r'[\s-]', '', isbn)
        params = {
            "func": "find-b",
            "find_code": "ISB",
            "request": clean_isbn,
            "local_base": "NLC01",
        }
        r = requests.get(NLC_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        detail_links = soup.select('a[href*="find_code=ISB"]')
        if not detail_links:
            return None

        detail_href = detail_links[0].get("href", "")
        if not detail_href:
            return None

        detail_url = f"https://opac.nlc.cn{detail_href}" if not detail_href.startswith('http') else detail_href
        r2 = requests.get(detail_url, headers=HEADERS, timeout=15)
        if r2.status_code != 200:
            return None

        detail_soup = BeautifulSoup(r2.text, "html.parser")
        result: Dict[str, str] = {"isbn": isbn}

        text = detail_soup.get_text()
        author_m = re.search(r'200\s+\d+\#\$a[^$]*\$f([^$]+)', text)
        if author_m:
            result["author"] = author_m.group(1).strip()

        pub_m = re.search(r'210\s+\d+\#\$a[^$]*\$c([^$]+)', text)
        if pub_m:
            result["publisher"] = pub_m.group(1).strip()

        year_m = re.search(r'210\s+\d+\#\$[a-d]*\$d(\d{4})', text)
        if year_m:
            result["year"] = year_m.group(1).strip()

        return result if len(result) > 1 else None
    except Exception:
        return None


def _crawl_isbn_sync(title: str) -> Optional[str]:
    try:
        clean_title = re.sub(r'[（(][^)）]*[)）]', '', title).strip()
        clean_title = re.sub(r'[=＝].*$', '', clean_title).strip()

        params = {
            "func": "find-b",
            "find_code": "WRD",
            "request": clean_title,
            "local_base": "NLC01",
        }

        r = requests.get(NLC_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        isbn = _extract_isbn_from_soup(soup)
        if isbn:
            return isbn

        detail_links = soup.select('a[href*="find_code=ISB"]')
        for link in detail_links[:3]:
            try:
                href = link.get("href", "")
                if href:
                    detail_url = f"http://opac.nlc.cn{href}" if href.startswith("/") else href
                    dr = requests.get(detail_url, headers=HEADERS, timeout=10)
                    if dr.status_code == 200:
                        dsoup = BeautifulSoup(dr.text, "html.parser")
                        detail_isbn = _extract_isbn_from_soup(dsoup)
                        if detail_isbn:
                            return detail_isbn
            except Exception:
                continue

        return None
    except Exception:
        return None


def _extract_isbn_from_soup(soup: BeautifulSoup) -> Optional[str]:
    text_content = soup.get_text()

    isbn_patterns = [
        r'ISBN[:\s]*([\d\-]{10,17})',
        r'978[\d\-]{10,14}',
        r'979[\d\-]{10,14}',
        r'[\d]{13}',
    ]

    for pattern in isbn_patterns:
        match = re.search(pattern, text_content, re.IGNORECASE)
        if match:
            raw = match.group(1) if "ISBN" in pattern else match.group(0)
            isbn = re.sub(r'[^\d]', '', raw)
            if len(isbn) == 13 or len(isbn) == 10:
                return isbn

    for td in soup.find_all("td"):
        txt = td.get_text(strip=True)
        for pattern in isbn_patterns:
            match = re.search(pattern, txt, re.IGNORECASE)
            if match:
                raw = match.group(1) if "ISBN" in pattern else match.group(0)
                isbn = re.sub(r'[^\d]', '', raw)
                if len(isbn) == 13 or len(isbn) == 10:
                    return isbn

    return None


def crawl_toc_sync(isbn: str) -> Optional[str]:
    """从 NLC OPAC 获取目录(330/327字段)。"""
    if not isbn:
        return None
    try:
        params = {
            "func": "find-b",
            "find_code": "ISB",
            "request": isbn,
            "local_base": "NLC01",
        }
        r = requests.get(NLC_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        detail_link = soup.select_one('a[href*="find_code=ISB"]')
        if not detail_link:
            return None
        href = detail_link.get("href", "")
        detail_url = f"http://opac.nlc.cn{href}" if href.startswith("/") else href
        dr = requests.get(detail_url, headers=HEADERS, timeout=10)
        if dr.status_code != 200:
            return None
        dsoup = BeautifulSoup(dr.text, "html.parser")
        for td in dsoup.select("td.td1"):
            text = td.get_text(strip=True)
            if text.startswith("330") or text.startswith("327"):
                toc_td = td.find_next_sibling("td")
                if toc_td:
                    toc_text = toc_td.get_text(strip=True)
                    if toc_text and len(toc_text) > 20:
                        return toc_text
        return None
    except Exception:
        return None


async def crawl_toc(isbn: str) -> Optional[str]:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, crawl_toc_sync, isbn)
    except Exception:
        return None
