"""Douban book metadata + TOC scraper."""
import re
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List

DOUBAN_SEARCH = "https://www.douban.com/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _search_by_isbn(isbn: str) -> Optional[str]:
    """Search Douban by ISBN and return the first book detail URL."""
    params = {"cat": "1001", "q": isbn}
    try:
        r = requests.get(DOUBAN_SEARCH, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.nbg"):
            href = a.get("href", "")
            if "book.douban.com/subject/" in href:
                return href
        for a in soup.select("div.result-list a[href*='subject']"):
            href = a.get("href", "")
            if "/subject/" in href:
                return href
    except Exception:
        pass
    return None


def _parse_douban_book(html: str) -> Dict[str, Any]:
    """Parse Douban book detail page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, Any] = {}

    title_el = soup.select_one("span[property='v:itemreviewed']")
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    authors = []
    for span in soup.select("span.pl"):
        text = span.get_text(strip=True)
        if text.startswith("作者"):
            parent = span.find_parent()
            if parent:
                for author_a in parent.select("a"):
                    name = author_a.get_text(strip=True)
                    if name:
                        authors.append(name)
    result["authors"] = authors

    pub_info = []
    for span in soup.select("span.pl"):
        text = span.get_text(strip=True)
        if any(text.startswith(kw) for kw in ["出版社", "出版年", "ISBN"]):
            tail = _get_tail(span)
            if tail:
                pub_info.append(f"{text}:{tail}")
    result["pub_info"] = pub_info

    isbn_el = soup.select_one("span.pl:-soup-contains('ISBN')")
    if isbn_el:
        tail = _get_tail(isbn_el)
        if tail:
            m = re.search(r'\d{10,13}', tail)
            if m:
                result["isbn"] = m.group(0)

    rating_el = soup.select_one("strong[property='v:average']")
    if rating_el:
        try:
            result["rating"] = float(rating_el.get_text(strip=True))
        except ValueError:
            pass

    intro_el = soup.select_one("div.intro")
    if intro_el:
        result["description"] = intro_el.get_text(strip=True)[:2000]

    tags = []
    for a in soup.select("a.tag"):
        tag = a.get_text(strip=True)
        if tag:
            tags.append(tag)
    result["tags"] = tags

    toc = _extract_toc(soup)
    if toc:
        result["toc"] = toc

    return result


def _extract_toc(soup: BeautifulSoup) -> Optional[str]:
    """Extract table of contents from Douban book page."""
    # Hidden full TOC div
    toc_div = soup.select_one("div#dir_72144_full")
    if not toc_div:
        toc_div = soup.select_one("div.indent div#dir_72144_full")
    if toc_div:
        text = toc_div.get_text(strip=True)
        if text:
            return text

    # Short TOC display with label
    for div in soup.select("div.indent"):
        label_span = div.select_one("span.pl")
        if label_span and "目录" in label_span.get_text():
            texts = []
            for child in div.children:
                if hasattr(child, 'get_text'):
                    t = child.get_text(strip=True)
                    if t and "目录" not in t:
                        texts.append(t)
                elif isinstance(child, str):
                    t = child.strip()
                    if t:
                        texts.append(t)
            text = "\n".join(texts)
            if text and len(text) > 10:
                return text[:5000]

    return None


def _get_tail(element) -> str:
    texts = []
    for sibling in element.next_siblings:
        if hasattr(sibling, 'get_text'):
            t = sibling.get_text(strip=True)
            if t:
                texts.append(t)
        elif isinstance(sibling, str):
            t = sibling.strip()
            if t:
                texts.append(t)
    return "".join(texts)


def fetch_douban(isbn: str) -> Optional[Dict[str, Any]]:
    """Fetch Douban book metadata by ISBN. Returns dict or None."""
    if not isbn:
        return None
    try:
        url = _search_by_isbn(isbn)
        if not url:
            return None
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        data = _parse_douban_book(r.text)
        data["url"] = url
        return data if data.get("title") else None
    except Exception:
        return None


def fetch_douban_by_title(title: str) -> Optional[Dict[str, Any]]:
    """Fetch Douban book metadata by title (fallback when ISBN unavailable)."""
    if not title or len(title.strip()) < 2:
        return None
    try:
        # Search Douban by title
        params = {"cat": "1001", "q": title.strip()}
        r = requests.get(DOUBAN_SEARCH, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        url = None
        for a in soup.select("a.nbg"):
            href = a.get("href", "")
            if "book.douban.com/subject/" in href:
                url = href
                break
        if not url:
            for a in soup.select("div.result-list a[href*='subject']"):
                href = a.get("href", "")
                if "/subject/" in href:
                    url = href
                    break
        if not url:
            return None
        r2 = requests.get(url, headers=HEADERS, timeout=15)
        if r2.status_code != 200:
            return None
        data = _parse_douban_book(r2.text)
        data["url"] = url
        return data if data.get("title") else None
    except Exception:
        return None
