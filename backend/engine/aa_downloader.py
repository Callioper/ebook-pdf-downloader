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
) -> List[Dict[str, Any]]:
    """搜索 Anna's Archive，返回所有MD5条目（含文件大小）"""
    results = []
    encoded = query.replace(" ", "+")
    search_url = f"{base_url}/search?q={encoded}"

    html = await _get_page_with_flare(search_url, proxy)
    if not html:
        # 尝试其他域名
        for alt_url in AA_BASE_URLS[1:]:
            alt_search = f"{alt_url}/search?q={encoded}"
            html = await _get_page_with_flare(alt_search, proxy)
            if html and len(html) > 500:
                base_url = alt_url
                break
    if not html:
        logger.warning(f"AA search failed for query: {query}")
        return results

    # 提取 MD5 链接和文件大小
    # AA 搜索结果的典型模式: href="/md5/<32hex>" 旁边有文件大小标签
    # Pattern 1: href="/md5/..." followed by size info
    md5_pattern = re.findall(
        r'href="/md5/([a-f0-9]{32})"[^>]*>.*?'
        r'<span[^>]*class="[^"]*text-sm[^"]*"[^>]*>([^<]+)</span>',
        html, re.DOTALL,
    )
    for md5, size_text in md5_pattern:
        size_bytes = _parse_file_size(size_text.strip())
        results.append({"md5": md5, "size_bytes": size_bytes, "size_label": size_text.strip()})

    # Pattern 2: href="/md5/..." standalone (no size found inline)
    for md5 in re.findall(r'href="/md5/([a-f0-9]{32})"', html):
        if md5 not in {r["md5"] for r in results}:
            results.append({"md5": md5, "size_bytes": 0, "size_label": "unknown"})

    # 按文件大小降序排列（大的优先）
    results.sort(key=lambda x: x.get("size_bytes", 0), reverse=True)
    logger.info(f"AA search '{query}': found {len(results)} MD5 entries")
    return results[:max_results]


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
    """从 MD5 页面解析实际下载链接（非stacks路径）"""
    md5_url = f"{base_url}/md5/{md5}"
    html = await _get_page_with_flare(md5_url, proxy, timeout=30)
    if not html:
        return None

    # 尝试获取 /d/{md5} 重定向
    d_url = f"{base_url}/d/{md5}"
    d_html = await _get_page_with_flare(d_url, proxy, timeout=15)
    download_patterns = [
        r'href="(https?://[^"]*\.(?:pdf|epub|mobi)(?:\?[^"]*)?)"',
        r'href="(https?://[^"]*/(?:d|dl|get)/[^"]*)"',
        r'href="(https?://[^"]*annas-archive[^"]*/[a-f0-9]{32}[^"]*)"',
        r'data-(?:url|file|download|href)="(https?://[^"]*)"',
        r'href="(/d/[a-f0-9]{32})"',
    ]

    for html_content in [html, d_html] if d_html else [html]:
        if not html_content:
            continue
        for p in download_patterns:
            m = re.search(p, html_content, re.IGNORECASE)
            if m:
                url = m.group(1)
                if url.startswith("/"):
                    url = urljoin(base_url, url)
                if url.startswith("http"):
                    return url

    return None
