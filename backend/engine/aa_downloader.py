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
    max_results: int = 20,
    preferred_title: str = "",
    preferred_isbn: str = "",
) -> List[Dict[str, Any]]:
    """
    搜索 Anna's Archive，解析搜索结果卡片提取MD5+标题+大小。
    按标题相关性 + 文件大小排序返回。
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

    # 将页面按 md5 链接切分为独立的搜索结果区块
    # 每个结果卡片包含: href="/md5/<32hex>" + 标题文本 + 文件大小
    for m in re.finditer(r'href="/md5/([a-f0-9]{32})"', html):
        md5 = m.group(1)
        pos = m.start()
        # 向前/向后各取 1500 字符作为单个结果卡的上下文窗口
        start = max(0, pos - 500)
        end = min(len(html), pos + 1500)
        block = html[start:end]

        # 从区块中提取标题（优先 h3，其次 strong，再次链接内文本）
        title = ""
        title_m = re.search(r'<h\d[^>]*>([^<]+)</h\d>', block)
        if not title_m:
            title_m = re.search(r'<strong[^>]*>([^<]+)</strong>', block)
        if not title_m:
            # 取 `<a ... href="/md5/">` 标签内最深层的文本
            inner_m = re.search(r'href="/md5/' + md5 + r'"[^>]*>\s*([^<{][^<]{3,80}?)\s*<', block)
            if inner_m:
                title = inner_m.group(1).strip()
        else:
            title = title_m.group(1).strip()

        # 从区块中提取文件大小
        size_label = "unknown"
        size_bytes = 0
        size_m = re.search(r'(?:<span[^>]*>)?([\d.]+[\s]*(?:GB|MB|KB))', block, re.IGNORECASE)
        if size_m:
            size_label = size_m.group(1).strip()
            size_bytes = _parse_file_size(size_label)

        # 计算标题相关度
        relevance = 0
        if preferred_title and title:
            relevance = _calc_title_relevance(title, preferred_title)
        elif preferred_isbn:
            # 区块中包含 ISBN 时加分
            if preferred_isbn[:10] in block:
                relevance += 5

        results.append({
            "md5": md5,
            "title": title,
            "size_bytes": size_bytes,
            "size_label": size_label,
            "relevance": relevance,
        })

    # 去重
    seen = set()
    deduped = []
    for r in results:
        if r["md5"] not in seen:
            seen.add(r["md5"])
            deduped.append(r)

    # 排序：高相关度优先 → 大文件优先
    deduped.sort(key=lambda x: (x.get("relevance", 0), x.get("size_bytes", 0)), reverse=True)

    if preferred_title:
        relevant = [r for r in deduped if r.get("relevance", 0) >= 1]
        logger.info(f"AA search '{query}': {len(deduped)} entries ({len(relevant)} title-relevant)")
        # 把相關度>0的排在前面，剩下的按大小排
        deduped.sort(key=lambda x: (1 if x.get("relevance", 0) >= 1 else 0, x.get("size_bytes", 0)), reverse=True)
    else:
        logger.info(f"AA search '{query}': {len(deduped)} entries")

    return deduped[:max_results]


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
    """抓取 MD5 详情页，提取 zlib_id、filesize_bytes、isbn 等"""
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

    # 提取 zlib_id
    zlib_m = re.search(r'z-lib(?:rary)?.{0,20}/(\d+)', html)
    if not zlib_m:
        zlib_m = re.search(r'zlib_id["\s:]+(\d+)', html)
    if zlib_m:
        result["zlib_id"] = zlib_m.group(1)

    # 提取文件大小（字节）
    size_m = re.search(r'filesize_bytes["\s:]+(\d+)', html)
    if size_m:
        result["filesize_bytes"] = int(size_m.group(1))
    else:
        # 从 "File size:" 标签提取
        size_label_m = re.search(r'File\s*size[:\s]*<[^>]*>([^<]+)<', html, re.IGNORECASE)
        if size_label_m:
            result["filesize_bytes"] = _parse_file_size(size_label_m.group(1))

    # 提取 ISBN
    isbn_m = re.search(r'ISBN[:\s]*(\d[\d\-X]{9,})', html, re.IGNORECASE)
    if isbn_m:
        result["isbn"] = isbn_m.group(1).strip()

    # 提取扩展名
    ext_m = re.search(r'(?:filetype|extension|Format)[:\s]*<[^>]*>([a-z0-9]{2,6})<', html, re.IGNORECASE)
    if ext_m:
        result["extension"] = ext_m.group(1).lower()

    logger.debug(f"MD5 {md5}: zlib_id={result['zlib_id']}, size={result['filesize_bytes']}B")
    return result


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

    # Strategy 2: /d/{md5} redirect (follow 302 → actual CDN/file link)
    d_url = f"{base_url}/d/{md5}"
    d_html = await _get_page_with_flare(d_url, proxy, timeout=20)
    if d_html:
        url = _find_url_in_html(d_html)
        if url:
            return url

    # Strategy 3: /d/{md5} with HTTP redirect following
    try:
        import requests as _req
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        d_kwargs = {"timeout": 15, "headers": hdrs, "verify": False, "allow_redirects": True}
        if proxy:
            d_kwargs["proxies"] = {"http": proxy, "https": proxy}
        d_resp = _req.get(d_url, **d_kwargs)
        if d_resp.status_code == 200 and len(d_resp.history) > 0:
            # Followed redirects — the final URL might be a download
            final_url = d_resp.url
            if final_url != d_url and "annas-archive" not in final_url.lower():
                return final_url
    except Exception:
        pass

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
