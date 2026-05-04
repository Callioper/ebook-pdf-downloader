# ==== aa_downloader.py ====
# 职责：Anna's Archive 搜索和MD5提取，支持FlareSolverr反爬
# 入口函数：search_aa(), get_md5_details(), resolve_download_url()
# 依赖：engine.flaresolverr (get_page_content)
# 注意：AA有Cloudflare JS保护，必须通过FlareSolverr访问

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

AA_BASE_URLS = [
    "https://annas-archive.gd",
    "https://annas-archive.se",
    "https://annas-archive.org",
]

_auth_cache: Dict[str, Any] = {"data": None, "ts": 0}


def get_stacks_api_key() -> Optional[str]:
    """从 ~/.hermes/auth.json 读取 stacks API key，缓存1小时"""
    import json
    import os
    now = time.time()
    if _auth_cache["data"] and (now - _auth_cache["ts"] < 3600):
        return _auth_cache["data"]  # type: ignore[reportUnboundVariable]
    auth_paths = [
        os.path.expanduser("~/.hermes/auth.json"),
        os.path.join(os.path.expanduser("~"), ".hermes", "auth.json"),
    ]
    for p in auth_paths:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                key = data.get("STACKS_ADMIN_API_KEY", "")
                if key:
                    _auth_cache["data"] = key
                    _auth_cache["ts"] = now
                    return key
        except Exception:
            pass
    return None


async def _get_page_with_flare(url: str, proxy: str = "", timeout: int = 30) -> Optional[str]:
    """通过FlareSolverr获取页面（绕过Cloudflare），失败后直连"""
    try:
        from engine.flaresolverr import get_page_content
        result = await get_page_content(url, proxy)
        if result and "cf-browser-verification" not in result:
            return result
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"FlareSolverr page fetch failed: {e}")

    # 直连兜底
    import requests as _req
    try:
        h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        kwargs = {"timeout": timeout, "headers": h, "verify": False}
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        r = _req.get(url, **kwargs)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


async def search_aa(
    query: str,
    proxy: str = "",
    base_url: str = AA_BASE_URLS[0],
    max_results: int = 30,
) -> List[Dict[str, Any]]:
    """
    搜索 Anna's Archive，只提取 MD5 列表（标题匹配交给 get_md5_details）。
    模仿 Stacks 的思路：搜索结果页只找 MD5，详情页才是获取标题的地方。
    """
    results = []
    encoded = query.replace(" ", "+")
    search_url = f"{base_url}/search?q={encoded}"

    html = await _get_page_with_flare(search_url, proxy)
    if not html:
        for alt_url in AA_BASE_URLS[1:]:
            alt_search = f"{alt_url}/search?q={encoded}"
            html = await _get_page_with_flare(alt_search, proxy)
            if html and len(html) > 500:
                base_url = alt_url
                break
    if not html:
        logger.warning(f"AA search failed for query: {query}")
        return results

    # 只提取 MD5 链接（去重，保留出现顺序）
    seen = set()
    for m in re.finditer(r'href="/md5/([a-f0-9]{32})"', html):
        md5 = m.group(1)
        if md5 not in seen:
            seen.add(md5)
            results.append({"md5": md5})

    logger.info(f"AA search '{query}': found {len(results)} MD5 entries")
    return results[:max_results]


def _calc_title_relevance(title: str, preferred: str) -> int:
    """计算标题匹配度（0-100），基于字符重叠和关键词命中"""
    import unicodedata
    t = unicodedata.normalize("NFKC", title.lower()).strip()
    p = unicodedata.normalize("NFKC", preferred.lower()).strip()
    if not t or not p:
        return 0

    # 精确包含 → 最高分
    if p in t or t in p:
        return 100
    # 分词：检查有多少关键词匹配
    t_words = set(re.split(r'[\s,，、。．：；！？\-\u4e00-\u9fff]+', t))
    p_words = set(re.split(r'[\s,，、。．：；！？\-\u4e00-\u9fff]+', p))
    t_words.discard("")
    p_words.discard("")

    # CJK 字符重叠率（中文字符级别）
    t_chars = set(c for c in t if '\u4e00' <= c <= '\u9fff')
    p_chars = set(c for c in p if '\u4e00' <= c <= '\u9fff')
    if p_chars and t_chars:
        overlap = len(t_chars & p_chars) / max(len(p_chars), len(t_chars))
        char_score = int(overlap * 100)
    else:
        char_score = 0

    # 词级别重叠
    word_overlap = len(t_words & p_words)
    max_words = max(len(t_words), len(p_words), 1)
    word_score = int((word_overlap / max_words) * 100) if max_words > 0 else 0

    return max(char_score, word_score)


def _parse_file_size(label: str) -> int:
    """将文件大小标签（如 '15.2 MB'）转换为字节数"""
    label = label.strip().upper().replace(",", ".")
    m = re.match(r"([\d.]+)\s*(GB|MB|KB|B)", label)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2)
    mul = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    return int(val * mul.get(unit, 1))


async def get_md5_details(
    md5: str,
    proxy: str = "",
    base_url: str = AA_BASE_URLS[0],
) -> Dict[str, Any]:
    """
    抓取 MD5 详情页，提取 title、ISBN、extension、zlib_id、filesize_bytes 等。
    使用 BeautifulSoup 做稳健解析（模仿 Stacks 的 extract_from_title()）。
    """
    result = {
        "md5": md5,
        "zlib_id": "",
        "filesize_bytes": 0,
        "isbn": "",
        "title": "",
        "extension": "",
    }

    md5_url = f"{base_url}/md5/{md5}"
    html = await _get_page_with_flare(md5_url, proxy, timeout=30)
    if not html:
        for alt_url in AA_BASE_URLS[1:]:
            alt_md5 = f"{alt_url}/md5/{md5}"
            html = await _get_page_with_flare(alt_md5, proxy, timeout=30)
            if html and len(html) > 500:
                break
    if not html:
        return result

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')

        # ---- Title: 模仿 Stacks 提取页面标题 ----
        # Stacks 查找: div[class*="font-semibold"][class*="text-2xl"][class*="leading-[1.2]"]
        title_div = soup.find('div', class_=lambda x: x and 'font-semibold' in x and 'text-2xl' in x and 'leading-[1.2]' in x)
        if title_div:
            title = title_div.get_text(strip=True).replace('\u200b', '').strip()
            result["title"] = title

        # ---- ISBN: 查找 "ISBN" 标签后的文本 ----
        isbn_elem = soup.find(string=re.compile(r'ISBN\s*:', re.IGNORECASE))
        if isbn_elem:
            parent_td = isbn_elem.find_parent('td')
            if parent_td:
                next_td = parent_td.find_next_sibling('td')
                if next_td:
                    isbn_text = next_td.get_text(strip=True)
                    isbn_m = re.search(r'(\d[\d\-X]{9,})', isbn_text)
                    if isbn_m:
                        result["isbn"] = isbn_m.group(1).strip()

        # ---- Extension: 从 metadata div 中提取 ----
        # Stacks 查找: div[class*="text-gray-800"][class*="font-semibold"][class*="text-sm"][class*="mt-4"]
        meta_div = soup.find('div', class_=lambda x: x and 'text-gray-800' in x and 'font-semibold' in x and 'text-sm' in x and 'mt-4' in x)
        if meta_div:
            meta_text = meta_div.get_text(separator=' ', strip=True)
            for part in meta_text.split('·'):
                part = part.strip().upper()
                for ext in ('.PDF', '.EPUB', '.MOBI', '.DJVU', '.CBZ', '.CBR', '.ZIP'):
                    if part == ext.replace('.', '') or part == ext:
                        result["extension"] = ext.lower()
                        break

        # ---- Filepath 兜底（从 js-md5-codes-tabs-tab 中提取文件名） ----
        if not result["title"] or not result["extension"]:
            for a in soup.find_all('a', class_='js-md5-codes-tabs-tab'):
                spans = a.find_all('span')
                if len(spans) >= 2:
                    label_text = spans[0].get_text(strip=True)
                    if 'Filepath' in label_text:
                        filepath_text = spans[1].get_text(strip=True)
                        # 从路径中提取文件名
                        if '\\' in filepath_text:
                            filename = filepath_text.split('\\')[-1]
                        elif '/' in filepath_text:
                            filename = filepath_text.split('/')[-1]
                        else:
                            filename = filepath_text
                        if not result["title"] and filename:
                            result["title"] = filename.rsplit('.', 1)[0] if '.' in filename else filename
                        if not result["extension"] and '.' in filepath_text:
                            ext_guess = filepath_text.rsplit('.', 1)[-1].lower()
                            if ext_guess in ('pdf', 'epub', 'mobi', 'djvu', 'cbz', 'cbr', 'zip'):
                                result["extension"] = ext_guess

        # ---- zlib_id ----
        zlib_m = re.search(r'z-lib(?:rary)?.{0,20}/(\d+)', html)
        if not zlib_m:
            zlib_m = re.search(r'zlib_id["\s:]+(\d+)', html)
        if zlib_m:
            result["zlib_id"] = zlib_m.group(1)

        # ---- filesize_bytes ----
        size_m = re.search(r'filesize_bytes["\s:]+(\d+)', html)
        if size_m:
            result["filesize_bytes"] = int(size_m.group(1))
        else:
            size_label_m = re.search(r'File\s*size[:\s]*<[^>]*>([^<]+)<', html, re.IGNORECASE)
            if size_label_m:
                result["filesize_bytes"] = _parse_file_size(size_label_m.group(1))

        logger.debug(f"MD5 {md5}: title='{result['title'][:30]}', isbn={result['isbn']}, "
                     f"ext={result['extension']}, zlib={result['zlib_id']}")
    except ImportError:
        # BeautifulSoup 不可用时的 regex 兜底
        logger.warning("BeautifulSoup not available, falling back to regex extraction")
        _extract_md5_regex_fallback(result, html)
    except Exception as e:
        logger.warning(f"BeautifulSoup extraction failed for MD5 {md5}: {e}")
        _extract_md5_regex_fallback(result, html)

    return result


def _extract_md5_regex_fallback(result: Dict[str, Any], html: str):
    """当 BeautifulSoup 不可用时的 regex 兜底提取"""
    if not result["title"]:
        title_m = re.search(r'<h\d[^>]*>([^<]{3,100})</h\d>', html)
        if title_m:
            result["title"] = title_m.group(1).strip()
    if not result["isbn"]:
        isbn_m = re.search(r'ISBN[:\s]*(\d[\d\-X]{9,})', html, re.IGNORECASE)
        if isbn_m:
            result["isbn"] = isbn_m.group(1).strip()
    if not result["extension"]:
        ext_m = re.search(r'(?:filetype|extension|Format)[:\s]*<[^>]*>([a-z0-9]{2,6})<', html, re.IGNORECASE)
        if ext_m:
            result["extension"] = ext_m.group(1).lower()


def verify_md5(filepath: str, expected_md5: str) -> bool:
    """
    验证下载文件的 MD5 是否匹配。模仿 Stacks 的 calculate_md5()。
    如果不匹配，重命名文件为 *_MISMATCH.* 用于调试。
    """
    import hashlib
    import os

    if not os.path.exists(filepath):
        return False
    if not expected_md5 or len(expected_md5) != 32:
        return True  # 没有预期 MD5 时跳过验证

    try:
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hash_md5.update(chunk)
        file_md5 = hash_md5.hexdigest()

        if file_md5.lower() == expected_md5.lower():
            return True

        logger.warning(f"MD5 mismatch for {os.path.basename(filepath)}: "
                       f"expected {expected_md5}, got {file_md5}")
        # 保留文件用于调试（类似 Stacks 的 _MISMATCH 后缀）
        base, ext = os.path.splitext(filepath)
        mismatch_path = f"{base}.MISMATCH{ext}"
        try:
            os.rename(filepath, mismatch_path)
        except Exception:
            pass
        return False

    except Exception as e:
        logger.warning(f"MD5 verification failed for {filepath}: {e}")
        return False


async def resolve_download_url(
    md5: str,
    proxy: str = "",
    base_url: str = AA_BASE_URLS[0],
) -> Optional[str]:
    """从 MD5 页面解析实际下载链接（非stacks路径）。
    策略：
    1. MD5 页面的直接下载链接
    2. /d/{md5} 的重定向链
    3. Slow download 按钮的 onclick/data 属性
    4. 备用域名重试
    """
    def _find_url_in_html(html_text: str) -> Optional[str]:
        """在HTML文本中搜索所有可能的下载链接模式"""
        patterns = [
            # Direct file links (PDF/EPUB/MOBI)
            r'href="(https?://[^"]*\.(?:pdf|epub|mobi)(?:\?[^"]*)?)"',
            # AA download paths
            r'href="(https?://[^"]*/(?:d|dl|get)/[^"]*)"',
            r'href="(https?://[^"]*annas-archive[^"]*/[a-f0-9]{32}[^"]*)"',
            # AA slow download
            r'href="(https?://[^"]*/slow_download[^"]*)"',
            r'href="(https?://[^"]*/download/[^"]*)"',
            # Data attributes
            r'data-(?:url|file|download|href)="(https?://[^"]*)"',
            # Onclick window.open
            r"onclick=[\"']window\.open\(['\"]([^\"']+)['\"]",
            # Relative paths
            r'href="(/d/[a-f0-9]{32})"',
            r'href="(/get/[a-f0-9]{32})"',
            r'href="(/slow_download[^"]*)"',
            # Meta refresh / redirect
            r'<meta[^>]*url=([^"\'>]+)',
            r'window\.location\s*=\s*["\']([^"\']+)',
        ]
        for p in patterns:
            m = re.search(p, html_text, re.IGNORECASE)
            if m:
                url = m.group(1)
                if url.startswith("/"):
                    url = urljoin(base_url, url)
                if url.startswith("http"):
                    return url
        return None

    # Strategy 1: MD5 page direct
    md5_url = f"{base_url}/md5/{md5}"
    html = await _get_page_with_flare(md5_url, proxy, timeout=30)
    if html:
        url = _find_url_in_html(html)
        if url:
            return url

    # Strategy 2: /d/{md5} → CDN redirect via FlareSolverr session
    # AA's /d/{md5} returns a 302 redirect to CDN when accessed through a
    # browser with Cloudflare clearance. FlareSolverr handles the Cloudflare
    # challenge and follows the redirect. The FINAL URL (solution.url) is the
    # CDN URL, which is NOT behind Cloudflare.
    d_url = f"{base_url}/d/{md5}"
    try:
        import requests as _req
        from engine.flaresolverr import _flare_url, set_flare_port
        flare_url = _flare_url()
        session_name = f"aa_d_{int(time.time())}"

        # Create FlareSolverr session
        _req.post(flare_url, json={
            "cmd": "sessions.create", "session": session_name,
        }, timeout=5)

        # Request /d/{md5} through FlareSolverr session
        # FlareSolverr handles Cloudflare + follows HTTP redirects
        fs_resp = _req.post(flare_url, json={
            "cmd": "request.get",
            "url": d_url,
            "session": session_name,
            "maxTimeout": 60000,
        }, timeout=70)

        if fs_resp.status_code == 200:
            data = fs_resp.json()
            if data.get("status") == "ok":
                solution = data.get("solution", {})
                final_url = solution.get("url", "")
                # solution.url is the CDN URL after redirect (not AA domain)
                if final_url and final_url != d_url and "annas-archive" not in final_url.lower():
                    logger.info(f"AA /d/{md5} → CDN via FS: {final_url[:80]}")
                    return final_url
                # If no redirect, try extracting CDN from response HTML
                resp_body = solution.get("response", "")
                if resp_body:
                    cdn_m = re.search(r'window\.location\s*[=:]\s*["\']([^"\']+)["\']', resp_body)
                    if cdn_m:
                        cdn_rel = cdn_m.group(1)
                        cdn_url = urljoin(d_url, cdn_rel) if cdn_rel.startswith("/") else cdn_rel
                        if "annas-archive" not in cdn_url.lower():
                            logger.info(f"AA /d/{md5} → CDN from JS: {cdn_url[:80]}")
                            return cdn_url

        # Clean up session
        try:
            _req.post(flare_url, json={
                "cmd": "sessions.destroy", "session": session_name,
            }, timeout=3)
        except Exception:
            pass
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"AA /d/{md5} FS redirect failed: {e}")

    # Strategy 3: /d/{md5} raw HTML parsing (fallback when FlareSolverr not available)
    d_html = await _get_page_with_flare(d_url, proxy, timeout=20)
    if d_html:
        url = _find_url_in_html(d_html)
        if url:
            return url

    # Strategy 4: Try slow download route (AA's alternative download flow)
    for slow_path in [f"/slow_download?md5={md5}", f"/get/{md5}", f"/dl/{md5}"]:
        slow_url = f"{base_url}{slow_path}"
        slow_html = await _get_page_with_flare(slow_url, proxy, timeout=15)
        if slow_html:
            url = _find_url_in_html(slow_html)
            if url:
                return url

    # Strategy 5: Retry with alternate base URLs
    for alt_url in AA_BASE_URLS:
        if alt_url == base_url:
            continue
        alt_md5 = f"{alt_url}/md5/{md5}"
        alt_html = await _get_page_with_flare(alt_md5, proxy, timeout=30)
        if alt_html:
            url = _find_url_in_html(alt_html)
            if url:
                return url
        alt_d = f"{alt_url}/d/{md5}"
        alt_d_html = await _get_page_with_flare(alt_d, proxy, timeout=15)
        if alt_d_html:
            url = _find_url_in_html(alt_d_html)
            if url:
                return url

    return None
