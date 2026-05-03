import asyncio
import os
import re
from typing import Optional

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
