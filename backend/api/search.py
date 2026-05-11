# ==== search.py ====
# 职责：搜索API路由，支持本地数据库、Anna's Archive和ZLibrary搜索
# 入口函数：search_books(), get_config_api(), update_config_api(), zlib_fetch_tokens()
# 依赖：config, search_engine, version, engine.zlib_downloader
# 注意：包含FlareSolverr安装、OCR安装和更新检查功能

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import warnings
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

from fastapi import APIRouter, File, Query, Request, UploadFile
from pydantic import BaseModel

from config import get_config, init_config, update_config
from search_engine import search_engine, detect_database_paths
from version import VERSION, GITHUB_REPO

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

HTML_TAG_RE = re.compile(r'<[^>]+>')

FLARE_INSTALL_URL = "https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.4.6/flaresolverr_windows_x64.zip"
FLARE_MIRROR_URLS = [
    # GitHub mirror (for CN users where github.com is slow/unreachable)
    "https://ghproxy.net/https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.4.6/flaresolverr_windows_x64.zip",
    "https://github.moeyy.xyz/https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.4.6/flaresolverr_windows_x64.zip",
]

_flare_install_state: Dict[str, Any] = {
    "downloading": False,
    "progress": 0.0,
    "status": "idle",
    "error": None,
    "path": None,
}

_flare_dl_state: Dict[str, Any] = {
    "downloaded": 0,
    "total": 0,
    "done": False,
    "error": "",
    "status": "idle",
    "install_path": "",
}
# Persistent install path, survives _flare_dl_state resets
_flare_last_install_path: str = ""


def _flare_report_progress(block_count, block_size, total_size):
    global _flare_dl_state
    _flare_dl_state["downloaded"] = min(block_count * block_size, total_size)
    _flare_dl_state["total"] = total_size


class ProxyRequest(BaseModel):
    http_proxy: str = ""


class ZLibFetchTokensRequest(BaseModel):
    email: str
    password: str


class InstallOCRRequest(BaseModel):
    engine: str = "tesseract"
    language_pack: str = ""


class InstallFlareRequest(BaseModel):
    install_path: str = ""


def _extract_aa_search_metadata(html: str) -> List[Dict[str, Any]]:
    """Extract book metadata from Anna's Archive search results page HTML.
    Search result cards contain: title, author, year, publisher, format, size, language."""
    results = []
    seen = set()
    # Each result is typically in a div with href to /md5/...
    for m in re.finditer(r'href="/md5/([a-f0-9]{32})"[^>]*>\s*([^<]+)', html):
        md5 = m.group(1)
        if md5 in seen:
            continue
        seen.add(md5)
        book: Dict[str, Any] = {"md5": md5, "source": "annas_archive",
                                "md5_url": f"https://annas-archive.gd/md5/{md5}"}
        # Extract title from the link text
        title = HTML_TAG_RE.sub('', m.group(2)).strip()
        if title:
            book["title"] = title
        results.append(book)

    if not results:
        return results

    # Parse search result cards for additional metadata
    # Split by md5 links to get individual result blocks
    blocks = re.split(r'<a[^>]*href="/md5/[a-f0-9]{32}"', html)
    if len(blocks) <= 1:
        return results

    # Skip first block (before first result)
    for i, block in enumerate(blocks[1:], start=0):
        if i >= len(results):
            break
        book = results[i]
        # Extract year - look for 4-digit year near "year" or similar labels
        year_m = re.search(r'(?:年|Year|year|Published)[^：:>]*[：:>]\s*(?:<[^>]+>)*(\d{4})', block)
        if year_m:
            book["year"] = year_m.group(1)
        # Extract publisher
        pub_m = re.search(r'(?:出版社?|Publisher|publisher|Published by)[^：:>]*[：:>]\s*(?:<[^>]+>)*([^<\n]+)', block)
        if pub_m:
            book["publisher"] = pub_m.group(1).strip()
        # Extract format/extension
        fmt_m = re.search(r'(?:格式|文件类型|Format|format|Extension|类型)[^：:>]*[：:>]\s*(?:<[^>]+>)*(\w+)', block)
        if fmt_m:
            book["format"] = fmt_m.group(1).strip().lower()
        if not book.get("format"):
            bare = re.search(r'\.(pdf|epub|mobi|azw3|djvu|txt)\b', block, re.I)
            if bare:
                book["format"] = bare.group(1).lower()
        # Extract file size
        size_m = re.search(r'(?:大小|文件大小|Size|size|File\s*size|文件大小)[^：:>]*[：:>]\s*(?:<[^>]+>)*([\d. ]+\s*(?:MB|GB|KB|MiB|GiB|B))', block)
        if size_m:
            book["size"] = size_m.group(1).strip()
        if not book.get("size"):
            bare_s = re.search(r'(\d+(?:\.\d+)?\s*(?:MB|GB|KB|MiB|GiB))\b', block, re.I)
            if bare_s:
                book["size"] = bare_s.group(1).strip()
        # Extract author
        auth_m = re.search(r'(?:作者|Author|author)[^：:>]*[：:>]\s*(?:<[^>]+>)*([^<\n]+)', block)
        if auth_m:
            book["author"] = auth_m.group(1).strip()
        # Extract language
        lang_m = re.search(r'(?:语言|Language|lang|Language)[^：:>]*[：:>]\s*(?:<[^>]+>)*(\w+)', block)
        if lang_m:
            book["language"] = lang_m.group(1).strip()
        # Extract ISBN
        isbn_m = re.search(r'[Ii][Ss][Bb][Nn][^：:>]*[：:>]\s*(?:<[^>]+>)*([\dX-]+)', block)
        if isbn_m:
            book["isbn"] = isbn_m.group(1).strip()

    return results


def _search_annas_archive(query: str, proxy: str = "") -> List[Dict[str, Any]]:
    encoded = urllib.parse.quote(query)
    url = f"https://annas-archive.gd/search?q={encoded}"
    try:
        import requests as _requests
        kwargs = {
            "timeout": 15,
            "headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            "verify": False,
        }
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        resp = _requests.get(url, **kwargs)
        if resp.status_code == 200:
            results = _extract_aa_search_metadata(resp.text)
            if not results:
                # Fallback: old behavior - only extract MD5 links
                seen = set()
                for m in re.finditer(r'href="/md5/([a-f0-9]{32})"', resp.text):
                    md5 = m.group(1)
                    if md5 not in seen:
                        seen.add(md5)
                        results.append({"md5": md5, "source": "annas_archive",
                                        "md5_url": f"https://annas-archive.gd/md5/{md5}"})
            return results
    except Exception as e:
        logger.warning(f"Failed to search Anna's Archive: {e}")
    return []


def _fetch_md5_page_info(md5: str, proxy: str = "") -> Dict[str, Any]:
    info: Dict[str, Any] = {"md5": md5, "source": "annas_archive"}
    url = f"https://annas-archive.gd/md5/{md5}"
    try:
        import requests as _requests
        kwargs = {
            "timeout": 15,
            "headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            "verify": False,
        }
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        resp = _requests.get(url, **kwargs)
        if resp.status_code != 200:
            return info
        html = resp.text
        title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
        if title_m:
            raw_title = HTML_TAG_RE.sub('', title_m.group(1)).strip()
            info["title"] = raw_title
        # More flexible patterns - handle various HTML structures on AA pages
        patterns = [
            (r'Author[s]?[：:\s>]*(?:<[^>]+>)*([^<>\n]{2,80})', "author"),
            (r'(?:Language|语言)[：:\s>]*(?:<[^>]+>)*([A-Za-z\u4e00-\u9fff]{2,20})', "language"),
            (r'(?:Format|格式|Extension|类型)[：:\s>]*(?:<[^>]+>)*(\w+)', "format"),
            (r'(?:File\s*size|Size|文件大小|大小)[：:\s>]*(?:<[^>]+>)*([\d. ]+\s*(?:MB|GB|KB|MiB|GiB|B))', "size"),
            (r'(?:Year|年份|Published)[：:\s>]*(?:<[^>]+>)*(\d{4})', "year"),
            (r'[Ii][Ss][Bb][Nn][：:\s>]*(?:<[^>]+>)*([\dX-]{10,17})', "isbn"),
            (r'(?:Publisher|出版社|Published by)[：:\s>]*(?:<[^>]+>)*([^<>\n]{2,100})', "publisher"),
        ]
        # Also try JSON-LD structured data
        jsonld_m = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        if jsonld_m:
            try:
                import json
                ld = json.loads(jsonld_m.group(1))
                if isinstance(ld, dict):
                    if not info.get("title"):
                        info["title"] = ld.get("name", "")
                    if not info.get("author") and ld.get("author"):
                        auth = ld["author"]
                        if isinstance(auth, list):
                            info["author"] = ", ".join(a.get("name", "") for a in auth if isinstance(a, dict))
                        elif isinstance(auth, dict):
                            info["author"] = auth.get("name", "")
                    if not info.get("publisher") and ld.get("publisher"):
                        pub = ld["publisher"]
                        info["publisher"] = pub.get("name", "") if isinstance(pub, dict) else str(pub)
                    if not info.get("isbn"):
                        info["isbn"] = ld.get("isbn", "")
                    if not info.get("year"):
                        info["year"] = ld.get("datePublished", "")[:4]
                    if not info.get("language"):
                        info["language"] = ld.get("inLanguage", "")
            except Exception:
                pass
        for pattern, key in patterns:
            if key in info:
                continue
            m = re.search(pattern, html)
            if m:
                val = m.group(1).strip()
                if val:
                    info[key] = val
        if "title" not in info:
            info["title"] = md5
    except Exception as e:
        logger.warning(f"Failed to fetch MD5 page info for {md5}: {e}")
        if "title" not in info:
            info["title"] = md5
    return info


async def _search_zlib(query: str, proxy: str = "") -> List[Dict[str, Any]]:
    config = get_config()
    email = config.get("zlib_email", "")
    password = config.get("zlib_password", "")
    if not email or not password:
        return []
    try:
        from engine.zlib_downloader import ZLibDownloader
        dl = ZLibDownloader(config)
        result = await dl.zlib_search(query, page=1, limit=10)
        books = []
        # Handle multiple possible result key names from Z-Lib eAPI
        items = result.get("books") or result.get("results") or result.get("data") or []
        if isinstance(items, dict):
            items = items.get("books", items.get("results", []))
        for item in (items if isinstance(items, list) else [])[:10]:
            if not item.get("title"):
                continue
            fmt = str(item.get("extension", item.get("format", ""))).lower()
            if fmt and fmt != "pdf":
                continue
            books.append({
                "source": "zlibrary",
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                "isbn": item.get("isbn", ""),
                "publisher": item.get("publisher", ""),
                "year": str(item.get("year", "")),
                "language": item.get("language", ""),
                "format": fmt,
                "size": item.get("filesize", item.get("size", "")),
                "md5": item.get("md5", ""),
                "book_id": str(item.get("id", "")),
            })
        return books
    except Exception as e:
        logger.warning(f"Failed to search ZLibrary: {e}")
        return []


@router.get("/search")
async def search_books(
    request: Request,
    field: str = Query(default="title"),
    query: str = Query(default=""),
    fuzzy: bool = Query(default=True),
    fields: Optional[List[str]] = Query(default=None, alias="fields[]"),
    queries: Optional[List[str]] = Query(default=None, alias="queries[]"),
    logics: Optional[List[str]] = Query(default=None, alias="logics[]"),
    fuzzies: Optional[List[str]] = Query(default=None, alias="fuzzies[]"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    config = get_config()
    db_path = config.get("ebook_db_path", "")
    search_engine.set_db_dir(db_path)

    result = search_engine.search(
        field=field,
        query=query,
        fuzzy=fuzzy,
        fields=fields,
        queries=queries,
        logics=logics,
        fuzzies=fuzzies,
        page=page,
        page_size=page_size,
    )

    is_advanced = bool(fields or queries)
    total = result.get("total", 0)
    external_books: List[Dict[str, Any]] = []

    if total == 0 and query and query.strip():
        proxy = config.get("http_proxy", "")
        import concurrent.futures

        def _run_aa():
            results = []
            try:
                md5_list = _search_annas_archive(query, proxy)
                for item in md5_list[:5]:
                    try:
                        info = _fetch_md5_page_info(item["md5"], proxy)
                        # Merge: keep search-page fields, fill gaps with MD5 page info
                        merged = {**item, **{k: v for k, v in info.items() if v}}
                        if merged.get("title"):
                            fmt = str(merged.get("format", "")).lower()
                            if fmt and fmt != "pdf":
                                continue  # skip non-PDF formats
                            if not fmt:
                                title_lower = merged.get("title", "").lower()
                                if any(ext in title_lower for ext in (".epub", ".mobi", ".azw", ".djvu")):
                                    continue
                            results.append(merged)
                    except Exception as e:
                        logger.warning(f"Failed to fetch MD5 info in _run_aa: {e}")
            except Exception as e:
                logger.warning(f"Failed to run Anna's Archive search: {e}")
            return results

        def _run_zlib():
            try:
                return asyncio.new_event_loop().run_until_complete(_search_zlib(query, proxy))
    except Exception as e:
        logger.error(f"open tools folder failed: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/system-status")
async def system_status():
    """Check all system component statuses in one call."""
    import os as _os, httpx as _httpx
    cfg = get_config()
    result = {"components": {}, "all_ok": True, "failures": [], "ocr_engine": cfg.get("ocr_engine", "tesseract")}

    # 1. Database status
    db_path = cfg.get("ebook_db_path", "")
    dbs_found = []
    if db_path and _os.path.isdir(db_path):
        for f in ["DX_2.0-5.0.db", "DX_6.0.db"]:
            if _os.path.isfile(_os.path.join(db_path, f)):
                dbs_found.append(f)
    result["components"]["database"] = {"ok": len(dbs_found) > 0, "detail": f"{len(dbs_found)} db(s)" if dbs_found else "未检测到"}
    if not dbs_found:
        result["failures"].append("数据库")

    # 2. Z-Library login
    zl_email = cfg.get("zlib_email", "")
    zl_pass = cfg.get("zlib_password", "")
    if zl_email and zl_pass:
        try:
            from engine.zlib_downloader import ZLibDownloader
            dl = ZLibDownloader(cfg)
            zl_r = await dl.zlib_login(zl_email, zl_pass)
            zl_ok = zl_r.get("ok", False)
            zl_balance = zl_r.get("balance", "")
            result["components"]["zlib"] = {"ok": zl_ok, "detail": zl_balance if zl_ok else "登录失败"}
            if not zl_ok:
                result["failures"].append("Z-Library")
        except Exception as e:
            result["components"]["zlib"] = {"ok": False, "detail": str(e)[:50]}
            result["failures"].append("Z-Library")
    else:
        result["components"]["zlib"] = {"ok": False, "detail": "未配置"}

    # 3. Stacks login
    stacks_url = cfg.get("stacks_base_url", "")
    stacks_user = cfg.get("stacks_username", "")
    stacks_pass = cfg.get("stacks_password", "")
    if stacks_url:
        try:
            async with _httpx.AsyncClient(timeout=5) as c:
                hr = await c.get(f"{stacks_url}/api/health")
                if hr.status_code != 200:
                    result["components"]["stacks"] = {"ok": False, "detail": f"服务 HTTP {hr.status_code}"}
                    result["failures"].append("Stacks")
                elif stacks_user and stacks_pass:
                    lr = await c.post(f"{stacks_url}/login", json={"username": stacks_user, "password": stacks_pass})
                    result["components"]["stacks"] = {"ok": lr.status_code == 200, "detail": "已登录" if lr.status_code == 200 else f"登录 HTTP {lr.status_code}"}
                    if lr.status_code != 200:
                        result["failures"].append("Stacks")
                else:
                    result["components"]["stacks"] = {"ok": hr.status_code == 200, "detail": "可连接（未配置登录）"}
        except Exception as e:
            result["components"]["stacks"] = {"ok": False, "detail": str(e)[:50]}
            result["failures"].append("Stacks")
    else:
        result["components"]["stacks"] = {"ok": False, "detail": "未配置"}

    # 4. FlareSolverr
    flaresolverr_port = cfg.get("flaresolverr_port", 8191)
    try:
        async with _httpx.AsyncClient(timeout=5) as c:
            fr = await c.get(f"http://localhost:{flaresolverr_port}")
            result["components"]["flaresolverr"] = {"ok": fr.status_code in (200, 404), "detail": f"端口 {flaresolverr_port}"}
    except Exception:
        result["components"]["flaresolverr"] = {"ok": False, "detail": f"端口 {flaresolverr_port} 不可达"}

    # 5. Proxy
    proxy = cfg.get("http_proxy", "")
    if proxy:
        try:
            async with _httpx.AsyncClient(timeout=6, proxy=proxy) as c:
                pr = await c.get("http://httpbin.org/ip")
                result["components"]["proxy"] = {"ok": pr.status_code == 200, "detail": proxy}
        except Exception as e:
            result["components"]["proxy"] = {"ok": False, "detail": str(e)[:50]}
            result["failures"].append("代理")
    else:
        result["components"]["proxy"] = {"ok": True, "detail": "直连（未配置代理）"}

    # 6. Source connectivity (AA + ZL)
    sources = {}
    for label, url in [("aa", "https://annas-archive.org"), ("zl_site", "https://z-lib.sk")]:
        try:
            async with _httpx.AsyncClient(timeout=8) as c:
                sr = await c.get(url)
                sources[label] = sr.status_code in (200, 301, 302)
        except Exception:
            sources[label] = False
    aa_ok = sources.get("aa", False)
    zl_site_ok = sources.get("zl_site", False)
    result["components"]["sources"] = {"ok": aa_ok or zl_site_ok, "detail": f"AA:{'√' if aa_ok else '×'} ZL:{'√' if zl_site_ok else '×'}"}
    if not aa_ok and not zl_site_ok:
        result["failures"].append("源站")

    # 7. Current OCR engine connectivity
    ocr_engine = cfg.get("ocr_engine", "tesseract")
    if ocr_engine == "mineru":
        token = cfg.get("mineru_token", "")
        if token:
            try:
                async with _httpx.AsyncClient(timeout=10) as c:
                    mr = await c.get("https://mineru.net/api/v4/extract-results/batch/test", headers={"Authorization": f"Bearer {token}"})
                    result["components"]["ocr"] = {"ok": mr.status_code in (200, 404), "detail": f"MinerU API"}
                    if mr.status_code not in (200, 404):
                        result["failures"].append("MinerU")
            except Exception as e:
                result["components"]["ocr"] = {"ok": False, "detail": f"MinerU: {str(e)[:50]}"}
                result["failures"].append("MinerU")
        else:
            result["components"]["ocr"] = {"ok": False, "detail": "MinerU: 未配置 Token"}
            result["failures"].append("MinerU")
    elif ocr_engine == "paddleocr_online":
        token = cfg.get("paddleocr_online_token", "")
        if token:
            try:
                async with _httpx.AsyncClient(timeout=10) as c:
                    pr = await c.get("https://paddleocr.aistudio-app.com/api/v2/ocr/jobs", headers={"Authorization": f"bearer {token}"}, params={"limit": 1})
                    result["components"]["ocr"] = {"ok": pr.status_code in (200, 401), "detail": f"PaddleOCR-VL-1.5"}
                    if pr.status_code not in (200, 401):
                        result["failures"].append("PaddleOCR")
            except Exception as e:
                result["components"]["ocr"] = {"ok": False, "detail": f"PaddleOCR: {str(e)[:50]}"}
                result["failures"].append("PaddleOCR")
        else:
            result["components"]["ocr"] = {"ok": False, "detail": "PaddleOCR: 未配置 Token"}
            result["failures"].append("PaddleOCR")
    elif ocr_engine == "llm_ocr":
        endpoint = cfg.get("llm_ocr_endpoint", "")
        model = cfg.get("llm_ocr_model", "")
        if endpoint:
            try:
                async with _httpx.AsyncClient(timeout=8) as c:
                    for suffix in ("/v1/models", "/models"):
                        try:
                            lr = await c.get(f"{endpoint.rstrip('/')}{suffix}")
                            models = [m.get("id", "") for m in lr.json().get("data", [])]
                            has_model = model in models if model else len(models) > 0
                            result["components"]["ocr"] = {"ok": has_model, "detail": f"LLM: {len(models)} models, {model}" if has_model else f"LLM: {len(models)} models, {model} 未加载"}
                            break
                        except Exception:
                            pass
                    else:
                        result["components"]["ocr"] = {"ok": False, "detail": "LLM: 端点不可达"}
                        result["failures"].append("LLM OCR")
            except Exception as e:
                result["components"]["ocr"] = {"ok": False, "detail": f"LLM: {str(e)[:50]}"}
                result["failures"].append("LLM OCR")
        else:
            result["components"]["ocr"] = {"ok": False, "detail": "LLM: 未配置端点"}
    else:
        result["components"]["ocr"] = {"ok": True, "detail": f"本地引擎: {ocr_engine}"}

    # 8. AI Vision connectivity
    av_endpoint = cfg.get("ai_vision_endpoint", "")
    av_model = cfg.get("ai_vision_model", "")
    if av_endpoint:
        try:
            async with _httpx.AsyncClient(timeout=8) as c:
                for suffix in ("/v1/models", "/models"):
                    try:
                        avr = await c.get(f"{av_endpoint.rstrip('/')}{suffix}")
                        result["components"]["ai_vision"] = {"ok": True, "detail": f"AI Vision: OK"}
                        break
                    except Exception:
                        pass
                else:
                    result["components"]["ai_vision"] = {"ok": False, "detail": "AI Vision: 端点不可达"}
        except Exception as e:
            result["components"]["ai_vision"] = {"ok": False, "detail": f"AI Vision: {str(e)[:50]}"}
    else:
        result["components"]["ai_vision"] = {"ok": True, "detail": "未配置（不使用）"}

    result["all_ok"] = len(result["failures"]) == 0
    return result
