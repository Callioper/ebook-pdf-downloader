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
        year_m = re.search(r'(?:年|Year|year)[^：:]*[：:]\s*(\d{4})', block)
        if year_m:
            book["year"] = year_m.group(1)
        # Extract publisher
        pub_m = re.search(r'(?:出版社?|Publisher|publisher)[^：:]*[：:]\s*([^<\n]+)', block)
        if pub_m:
            book["publisher"] = pub_m.group(1).strip()
        # Extract format/extension
        fmt_m = re.search(r'(?:格式|文件类型|Format|format)[^：:]*[：:]\s*(\w+)', block)
        if fmt_m:
            book["format"] = fmt_m.group(1).strip()
        # Extract file size
        size_m = re.search(r'(?:大小|文件大小|Size|size)[^：:]*[：:]\s*([\d. ]+\s*(?:MB|GB|KB|MiB|GiB))', block)
        if size_m:
            book["size"] = size_m.group(1).strip()
        # Extract author
        auth_m = re.search(r'(?:作者|Author|author)[^：:]*[：:]\s*([^<\n]+)', block)
        if auth_m:
            book["author"] = auth_m.group(1).strip()
        # Extract language
        lang_m = re.search(r'(?:语言|Language|lang)[^：:]*[：:]\s*(\w+)', block)
        if lang_m:
            book["language"] = lang_m.group(1).strip()
        # Extract ISBN
        isbn_m = re.search(r'[Ii][Ss][Bb][Nn][^：:]*[：:]\s*([\dX-]+)', block)
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
            (r'Author[s]?[：:\s]*([^<>\n]{2,80})', "author"),
            (r'(?:Language|语言)[：:\s]*([A-Za-z]{2,20})', "language"),
            (r'(?:Format|格式)[：:\s]*(\w+)', "format"),
            (r'(?:File size|Size|文件大小)[：:\s]*([\d. ]+\s*(?:MB|GB|KB|MiB|GiB))', "size"),
            (r'(?:Year|年份)[：:\s]*(\d{4})', "year"),
            (r'[Ii][Ss][Bb][Nn][：:\s]*([\dX-]{10,17})', "isbn"),
            (r'(?:Publisher|出版社)[：:\s]*([^<>\n]{2,100})', "publisher"),
        ]
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
            books.append({
                "source": "zlibrary",
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                "isbn": item.get("isbn", ""),
                "publisher": item.get("publisher", ""),
                "year": str(item.get("year", "")),
                "language": item.get("language", ""),
                "format": item.get("extension", item.get("format", "")),
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
                for item in md5_list[:3]:
                    try:
                        info = _fetch_md5_page_info(item["md5"], proxy)
                        if info.get("title"):
                            results.append(info)
                    except Exception as e:
                        logger.warning(f"Failed to fetch MD5 info in _run_aa: {e}")
            except Exception as e:
                logger.warning(f"Failed to run Anna's Archive search: {e}")
            return results

        def _run_zlib():
            try:
                return asyncio.new_event_loop().run_until_complete(_search_zlib(query, proxy))
            except Exception as e:
                logger.warning(f"Failed to run ZLibrary search: {e}")
                return []

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            future_aa = pool.submit(_run_aa)
            future_zlib = pool.submit(_run_zlib)
            try:
                external_books.extend(future_aa.result(timeout=6))
            except Exception:
                pass
            try:
                external_books.extend(future_zlib.result(timeout=6))
            except Exception:
                pass
        finally:
            pool.shutdown(wait=False)

    result["external_books"] = external_books
    return result


@router.get("/available-dbs")
async def available_dbs():
    config = get_config()
    db_path = config.get("ebook_db_path", "")
    search_engine.set_db_dir(db_path)
    dbs = search_engine.available_dbs()
    return {"dbs": dbs}


@router.get("/config")
async def get_config_endpoint():
    config = get_config()
    safe = dict(config)
    safe.pop("zlib_password", None)
    return safe


@router.post("/config")
async def update_config_endpoint(data: Dict[str, Any]):
    updated = update_config(data)
    safe = dict(updated)
    safe.pop("zlib_password", None)
    return safe


@router.post("/upload-cookies")
async def upload_cookies(file: UploadFile = File(...)):
    content = await file.read()
    data = json.loads(content)
    config = get_config()
    db_path = config.get("ebook_data_geter_path", "")
    cookie_file = os.path.join(db_path, "cookie-annas-archive-gd.json")
    with open(cookie_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "saved_to": cookie_file}


_browse_lock = threading.Lock()


def _run_folder_dialog() -> str:
    """Open native Windows folder picker via tkinter filedialog."""
    if os.name != "nt":
        return ""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        root.overrideredirect(True)
        root.geometry('0x0+0+0')
        root.lift()
        root.focus_force()
        root.update_idletasks()
        root.after(200, lambda: root.lift())
        path = filedialog.askdirectory(
            parent=root, title="Select database folder",
            mustexist=True,
        )
        root.destroy()
        return str(path) if path else ""
    except Exception:
        return ""


@router.get("/browse-folder")
async def browse_folder():
    if not _browse_lock.acquire(blocking=False):
        return {"path": "", "error": "dialog already open"}
    try:
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, _run_folder_dialog)
        if path:
            return {"path": path}
        return {"path": "", "error": "unable to open folder dialog"}
    finally:
        _browse_lock.release()


@router.get("/detect-paths")
async def detect_paths():
    loop = asyncio.get_running_loop()
    paths = await loop.run_in_executor(None, detect_database_paths)
    # Return just path strings (folder paths containing .db files), not dicts
    path_strings = []
    for p in paths:
        if isinstance(p, dict) and "path" in p:
            path_strings.append(p["path"])
        elif isinstance(p, str):
            path_strings.append(p)
    return {"paths": path_strings}


@router.get("/detect-nlc-paths")
async def detect_nlc_paths():
    candidates = []
    backend_nlc = Path(__file__).resolve().parent.parent / "nlc"
    if backend_nlc.exists():
        candidates.append(str(backend_nlc))

    config = get_config()
    db_path = config.get("ebook_db_path", "")
    if db_path:
        db_dir = Path(db_path)
        parents_to_check = [db_dir] + list(db_dir.parents)[:3]
        for parent in parents_to_check:
            if not parent.exists():
                continue
            nlc_dir = parent / "nlc"
            if nlc_dir.exists() and str(nlc_dir) not in candidates:
                candidates.append(str(nlc_dir))
            for child in parent.iterdir():
                if child.is_dir() and child.name.lower() == "nlc" and str(child) not in candidates:
                    candidates.append(str(child))

    return {"paths": candidates}


@router.get("/check-nlc-path")
async def check_nlc_path():
    config = get_config()
    nlc_path = config.get("ebook_data_geter_path", "")
    if not nlc_path:
        return {"ok": False, "message": "NLC 路径未配置", "exists": False}

    path = Path(nlc_path)
    if not path.exists():
        return {"ok": False, "message": f"路径不存在: {nlc_path}", "exists": False}

    if not path.is_dir():
        return {"ok": False, "message": f"路径不是目录: {nlc_path}", "exists": True}

    required_files = ["main.py", "nlc_isbn.py"]
    missing = [f for f in required_files if not (path / f).exists()]
    if missing:
        return {"ok": False, "message": f"缺少模块文件: {', '.join(missing)}", "exists": True, "missing": missing}

    return {"ok": True, "message": "NLC 模块路径有效", "exists": True}


@router.get("/status")
async def service_status():
    config = get_config()
    db_path = config.get("ebook_db_path", "")
    search_engine.set_db_dir(db_path)
    dbs = search_engine.available_dbs()
    reachable = len(dbs) > 0
    return {"ebookDatabase": {"reachable": reachable, "dbs": dbs}}


@router.post("/check-proxy")
async def check_proxy(body: ProxyRequest):
    proxy_url = body.http_proxy or get_config().get("http_proxy", "")
    if not proxy_url:
        return {"ok": True, "message": "未设置代理，使用本机网络"}
    try:
        import requests as _requests
        r = _requests.get("http://httpbin.org/ip", timeout=6, proxies={"http": proxy_url, "https": proxy_url}, verify=False)
        r.raise_for_status()
        # Persist proxy on success
        update_config({"http_proxy": proxy_url})
        return {"ok": True, "message": "代理可用"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.post("/check-proxy-sources")
async def check_proxy_sources(body: ProxyRequest):
    proxy_url = body.http_proxy or get_config().get("http_proxy", "")
    results = {}
    details = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    targets = [
        ("annas_archive", "https://annas-archive.org"),
        ("zlibrary", "https://z-lib.sk"),
        ("httpbin", "http://httpbin.org/ip"),
    ]

    def _check_url(url: str, proxy: str = "") -> Tuple[bool, str]:
        try:
            import requests as _requests
            kwargs = {"timeout": 15, "headers": headers, "verify": False}
            if proxy:
                kwargs["proxies"] = {"http": proxy, "https": proxy}
            resp = _requests.get(url, **kwargs)
            if resp.status_code in (200, 301, 302):
                return (True, "OK")
            if resp.status_code == 503:
                return (True, f"HTTP 503 (服务暂不可用)")
            return (False, f"HTTP {resp.status_code}")
        except _requests.HTTPError as e:
            return (False, f"HTTP {e.response.status_code}")
        except Exception as e:
            err_str = str(e).lower()
            if any(x in err_str for x in ["connection", "ssl", "timeout", "proxy", "resolve"]):
                return (True, f"连接问题: {str(e)[:60]}")
            return (False, str(e)[:100])

    def _check_aa_api(proxy: str = "") -> Tuple[bool, str]:
        """Try actual search on Anna's Archive to verify API works."""
        import requests as _requests
        kwargs = {"timeout": 20, "headers": headers, "verify": False}
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        try:
            resp = _requests.get("https://annas-archive.gd/search?q=test", **kwargs)
            if resp.status_code == 200:
                html = resp.text
                if re.search(r'href="/md5/([a-f0-9]{32})"', html):
                    return (True, "搜索API正常")
                return (True, "网站可达（搜索无结果）")
            return (True, f"网站可达 (HTTP {resp.status_code})")
        except Exception as e:
            return (False, f"搜索API不可用: {str(e)[:60]}")

    def _check_zl_api(proxy: str = "") -> Tuple[bool, str]:
        """Try Z-Library eapi health/version check."""
        import requests as _requests
        kwargs = {"timeout": 15, "headers": headers, "verify": False}
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        try:
            resp = _requests.get("https://z-lib.sk/eapi/book/search?message=test&limit=1", **kwargs)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and ("books" in data or "results" in data):
                    return (True, "搜索API正常")
                return (True, "API可达")
            return (True, f"网站可达 (HTTP {resp.status_code})")
        except Exception as e:
            return (False, f"搜索API不可用: {str(e)[:60]}")

    for name, url in targets:
        ok, detail = _check_url(url, proxy_url if proxy_url else "")
        results[name] = ok
        details[name] = detail

    # Deep API-level checks
    aa_ok, aa_api_detail = _check_aa_api(proxy_url if proxy_url else "")
    zl_ok, zl_api_detail = _check_zl_api(proxy_url if proxy_url else "")

    # Override with API-level detail when API check available
    if aa_ok:
        results["annas_archive"] = True
        details["annas_archive"] = aa_api_detail
    if zl_ok:
        results["zlibrary"] = True
        details["zlibrary"] = zl_api_detail

    return {"ok": True, "results": results, "details": details, "proxy_configured": bool(proxy_url)}


@router.post("/zlib-fetch-tokens")
async def zlib_fetch_tokens(body: ZLibFetchTokensRequest):
    try:
        from engine.zlib_downloader import ZLibDownloader
        config = get_config()
        dl = ZLibDownloader(config)
        result = await dl.zlib_login(body.email, body.password)
        # Persist credentials on success
        if result.get("ok"):
            update_config({"zlib_email": body.email, "zlib_password": body.password})
        return result
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.get("/check-zlib")
async def check_zlib():
    """Check if stored Z-Library credentials are still valid."""
    config = get_config()
    email = config.get("zlib_email", "")
    password = config.get("zlib_password", "")
    if not email or not password:
        return {"ok": False, "message": "未配置凭据"}
    try:
        from engine.zlib_downloader import ZLibDownloader
        dl = ZLibDownloader(config)
        result = await dl.zlib_login(email, password)
        return result
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.get("/check-proxy-status")
async def check_proxy_status():
    """Check if stored proxy is still valid."""
    config = get_config()
    proxy = config.get("http_proxy", "")
    if not proxy:
        return {"ok": False, "message": "未配置代理"}
    try:
        import requests as _requests
        r = _requests.get("http://httpbin.org/ip", timeout=6, proxies={"http": proxy, "https": proxy}, verify=False)
        if r.status_code == 200:
            return {"ok": True, "message": "代理可用"}
        return {"ok": False, "message": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:100]}


@router.get("/check-ocr")
async def check_ocr(engine: str = Query(default="")):
    config = get_config()
    if not engine:
        engine = config.get("ocr_engine", "tesseract")
    try:
        if engine == "ocrmypdf":
            result = subprocess.run(
                ["python", "-m", "ocrmypdf", "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                # Fallback: try plain ocrmypdf
                result = subprocess.run(["ocrmypdf", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return {"ok": True, "engine": "ocrmypdf", "version": result.stdout.strip().split("\n")[0]}
        elif engine == "tesseract":
            result = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                ver = result.stdout.split("\n")[0].strip()
                for prefix in ["tesseract v", "tesseract ", "v"]:
                    if ver.startswith(prefix):
                        ver = ver[len(prefix):]
                        break
                return {"ok": True, "engine": "tesseract", "version": ver}
            # Check common install paths (Tesseract may exist but not in PATH)
            found_path = None
            for tess_path in [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files\Tesseract-OCR\program\tesseract.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
                os.path.expandvars(r"%ProgramFiles%\Tesseract-OCR\tesseract.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\program\tesseract.exe"),
            ]:
                if os.path.exists(tess_path):
                    found_path = tess_path
                    break
            if not found_path:
                # Walk common install dirs
                for base_dir in [
                    r"C:\Program Files\Tesseract-OCR",
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR"),
                ]:
                    if os.path.isdir(base_dir):
                        for root, dirs, files in os.walk(base_dir):
                            for f in files:
                                if f.lower() == "tesseract.exe":
                                    found_path = os.path.join(root, f)
                                    break
                            if found_path:
                                break
                    if found_path:
                        break
            if found_path:
                try:
                    r = subprocess.run([found_path, "--version"], capture_output=True, text=True, timeout=5)
                    if r.returncode == 0:
                        # Add to PATH so subsequent calls work
                        os.environ["PATH"] = os.path.dirname(found_path) + os.pathsep + os.environ.get("PATH", "")
                        ver = r.stdout.split("\n")[0].strip()
                        for prefix in ["tesseract v", "tesseract ", "v"]:
                            if ver.startswith(prefix):
                                ver = ver[len(prefix):]
                                break
                        return {"ok": True, "engine": "tesseract", "version": ver, "note": "已自动添加到PATH"}
                except Exception:
                    pass
            # Check if winget has it registered
            if os.name == "nt":
                try:
                    r = subprocess.run(["winget", "list", "--exact", "--id", "UB-Mannheim.TesseractOCR"],
                                       capture_output=True, text=True, timeout=10)
                    if r.returncode == 0 and "Tesseract" in r.stdout:
                        return {"ok": False, "engine": "tesseract", "message": "Tesseract 已通过 winget 注册但可能未完整安装，点击安装按钮重新安装"}
                except FileNotFoundError:
                    pass
        elif engine == "easyocr":
            # Use system Python to check (pip install goes to system Python, not frozen exe)
            py = _pip_install_cmd()[0]
            r = subprocess.run([py, "-c", "import easyocr; print(easyocr.__version__)"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                ver = r.stdout.strip().split("\n")[0]
                return {"ok": True, "engine": "easyocr", "version": ver}
            try:
                import site; user_site = site.getusersitepackages()
                if user_site not in sys.path: sys.path.insert(0, user_site)
                import easyocr
                return {"ok": True, "engine": "easyocr"}
            except ImportError:
                pass
        elif engine == "paddleocr":
            # Use system Python to check (pip install goes to system Python)
            py = _pip_install_cmd()[0]
            r = subprocess.run([py, "-c", "import paddleocr; print(paddleocr.__version__)"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                ver = r.stdout.strip().split("\n")[0]
                return {"ok": True, "engine": "paddleocr", "version": ver if ver != "ok" else "已安装"}
            try:
                import site; user_site = site.getusersitepackages()
                if user_site not in sys.path: sys.path.insert(0, user_site)
                import paddleocr
                return {"ok": True, "engine": "paddleocr"}
            except ImportError:
                pass
        elif engine == "appleocr":
            if sys.platform != "darwin":
                return {"ok": False, "engine": "appleocr", "message": "AppleOCR 仅 macOS 支持"}
            try:
                result = subprocess.run(["which", "ocr"],
                    capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return {"ok": True, "engine": "appleocr"}
            except Exception:
                pass
            return {"ok": False, "engine": "appleocr", "message": "AppleOCR 未安装"}
        return {"ok": False, "engine": engine, "message": f"{engine} not found"}
    except FileNotFoundError:
        return {"ok": False, "engine": engine, "message": f"{engine} 未安装或不在 PATH 中"}
    except Exception as e:
        return {"ok": False, "engine": engine, "message": str(e)}


def _pip_install_cmd() -> List[str]:
    """Get the right command to run pip install, regardless of frozen status.
    In frozen mode, sys.executable is the exe (BookDownloader.exe), and
    'BookDownloader.exe -m pip install' would launch another BookDownloader instance.
    Instead, find system python from PATH and use --user flag.
    In dev mode (venv), use venv python directly (no --user, installs into venv)."""
    python_cmd = sys.executable
    user_flag = []  # dev mode: install into current python (no --user)
    if getattr(sys, 'frozen', False):
        user_flag = ["--user"]
        import shutil
        for candidate in ["python", "python3", "py"]:
            found = shutil.which(candidate)
            if found:
                python_cmd = found
                break
        if python_cmd == sys.executable:
            # No system Python found via shutil — try common Windows locations
            for candidate in [
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python314", "python.exe"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python313", "python.exe"),
                r"C:\Python314\python.exe",
                r"C:\Python313\python.exe",
            ]:
                if os.path.exists(candidate):
                    python_cmd = candidate
                    break
    return [python_cmd, "-m", "pip", "install"] + user_flag


@router.post("/install-ocr")
async def install_ocr(body: InstallOCRRequest):
    engine = body.engine
    try:
        if engine == "tesseract":
            # First check if Tesseract is already installed (even if not in PATH)
            for tess_path in [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files\Tesseract-OCR\program\tesseract.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\program\tesseract.exe"),
            ]:
                if os.path.exists(tess_path):
                    os.environ["PATH"] = os.path.dirname(tess_path) + os.pathsep + os.environ.get("PATH", "")
                    return {"ok": True, "message": f"Tesseract OCR 已存在于 {tess_path}，已添加至 PATH"}

            # Try multiple install methods
            try:
                if os.name == "nt":
                    # Method 1: winget (built-in on Win11)
                    try:
                        result = subprocess.run(
                            ["winget", "install", "--exact", "--id", "UB-Mannheim.TesseractOCR",
                             "--silent", "--accept-package-agreements", "--force"],
                            capture_output=True, text=True, timeout=120
                        )
                        if result.returncode == 0:
                            return {"ok": True, "message": "Tesseract OCR 安装成功（winget）"}
                    except FileNotFoundError:
                        pass

                    # Method 2: choco (chocolatey)
                    try:
                        result = subprocess.run(
                            ["choco", "install", "tesseract", "-y"],
                            capture_output=True, text=True, timeout=120
                        )
                        if result.returncode == 0:
                            return {"ok": True, "message": "Tesseract OCR 安装成功（choco）"}
                    except FileNotFoundError:
                        pass

                    # Method 3: Direct download from UB-Mannheim (with mirror fallback)
                    import requests as _requests
                    # Try known direct download URLs first (no API needed)
                    direct_urls = [
                        "https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe",
                        "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe",
                    ]
                    mirror_prefixes = [
                        "",  # direct
                        "https://ghproxy.net/",
                        "https://github.moeyy.xyz/",
                    ]
                    installer_path = None
                    for direct_url in direct_urls:
                        for prefix in mirror_prefixes:
                            dl_url = prefix + direct_url if prefix else direct_url
                            try:
                                tmp_dir = os.path.join(tempfile.gettempdir(), "book-downloader", "tesseract")
                                os.makedirs(tmp_dir, exist_ok=True)
                                installer_path = os.path.join(tmp_dir, "tesseract-setup.exe")
                                dl = _requests.get(dl_url, stream=True, timeout=120, verify=False)
                                dl.raise_for_status()
                                with open(installer_path, "wb") as f:
                                    for chunk in dl.iter_content(chunk_size=65536):
                                        if chunk:
                                            f.write(chunk)
                                # Verify it's really an exe
                                if os.path.getsize(installer_path) > 5 * 1024 * 1024:
                                    break  # success
                            except Exception:
                                installer_path = None
                                continue
                        if installer_path:
                            break

                    if installer_path and os.path.getsize(installer_path) > 5 * 1024 * 1024:
                        import ctypes
                        ret = ctypes.windll.shell32.ShellExecuteW(
                            None, "runas", installer_path,
                            "/S /D=C:\\Program Files\\Tesseract-OCR", None, 0
                        )
                        if ret > 32:
                            import time as _t
                            _t.sleep(5)
                            os.environ["PATH"] += os.pathsep + r"C:\Program Files\Tesseract-OCR"
                            return {"ok": True, "message": "Tesseract OCR 安装已启动（请确认 UAC 弹窗）"}
                return {"ok": False, "message": "请手动安装 Tesseract OCR:\n  winget install --id UB-Mannheim.TesseractOCR\n  choco install tesseract\n  或下载: https://github.com/UB-Mannheim/tesseract/releases"}
            except Exception as e:
                return {"ok": False, "message": f"自动安装失败: {str(e)[:100]}。请手动安装: https://github.com/UB-Mannheim/tesseract/wiki"}
        elif engine == "ocrmypdf":
            CREATE_NO_WINDOW = 0x08000000
            cmd = _pip_install_cmd() + ["ocrmypdf"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                creationflags=CREATE_NO_WINDOW,
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:] or result.stderr.strip()[-500:]}
        elif engine == "paddleocr":
            CREATE_NO_WINDOW = 0x08000000
            # Install paddleocr directly (NOT ocrmypdf-paddleocr which has paddlepaddle 3.x dependency issues)
            cmd = _pip_install_cmd() + ["paddleocr"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                creationflags=CREATE_NO_WINDOW,
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:] or result.stderr.strip()[-500:]}
        elif engine == "easyocr":
            CREATE_NO_WINDOW = 0x08000000
            cmd = _pip_install_cmd() + ["ocrmypdf-easyocr"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                creationflags=CREATE_NO_WINDOW,
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:] or result.stderr.strip()[-500:]}
        elif engine == "appleocr":
            if sys.platform != "darwin":
                return {"ok": False, "message": "AppleOCR 仅 macOS 支持"}
            cmd = _pip_install_cmd() + ["appleocr"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:]}
        else:
            return {"ok": False, "message": f"Unknown engine: {engine}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.post("/install-flare")
async def install_flare(body: InstallFlareRequest):
    global _flare_dl_state
    try:
        custom_path = body.install_path
        if not custom_path:
            # Default to program's tools directory for easy discovery
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            install_path = os.path.join(base_dir, "tools", "flaresolverr")
        else:
            install_path = custom_path

        global _flare_last_install_path
        _flare_last_install_path = install_path

        zip_path = os.path.join(install_path, "flaresolverr.zip")
        os.makedirs(install_path, exist_ok=True)
        _flare_dl_state["install_path"] = install_path

        def _do_download():
            global _flare_dl_state
            try:
                import requests as _requests
                _flare_dl_state["status"] = "downloading"
                _flare_dl_state["downloaded"] = 0
                _flare_dl_state["total"] = 0
                _flare_dl_state["done"] = False
                _flare_dl_state["error"] = ""

                # Try primary URL first, then mirrors
                urls_to_try = [FLARE_INSTALL_URL] + list(FLARE_MIRROR_URLS)
                last_error = ""
                for dl_url in urls_to_try:
                    try:
                        resp = _requests.get(dl_url, stream=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
                        resp.raise_for_status()
                        total = int(resp.headers.get("Content-Length", 0))
                        _flare_dl_state["total"] = total
                        downloaded = 0
                        with open(zip_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=65536):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    _flare_dl_state["downloaded"] = downloaded
                        _flare_dl_state["status"] = "extracting"
                        _flare_dl_state["done"] = True
                        last_error = ""
                        # Extract immediately in the download thread
                        try:
                            if os.path.getsize(zip_path) >= 100000:
                                import zipfile as _zipfile
                                with _zipfile.ZipFile(zip_path, "r") as _zf:
                                    _bad = _zf.testzip()
                                    if not _bad:
                                        _zf.extractall(install_path)
                                        _flare_dl_state["status"] = "done"
                                try:
                                    os.remove(zip_path)
                                except Exception:
                                    pass
                        except Exception as _ex:
                            _flare_dl_state["error"] = f"解压失败: {_ex}"
                            _flare_dl_state["status"] = "error"
                        break  # success, stop trying
                    except Exception as e:
                        last_error = str(e)
                        _flare_dl_state["status"] = "downloading"
                        _flare_dl_state["total"] = 0
                        _flare_dl_state["downloaded"] = 0
                        continue

                if last_error:
                    _flare_dl_state["error"] = f"所有下载地址均失败 (最后错误: {last_error[:100]})"
                    _flare_dl_state["done"] = True
                    _flare_dl_state["status"] = "error"
            except _requests.HTTPError as e:
                _flare_dl_state["error"] = f"下载失败 (HTTP {e.response.status_code})"
                _flare_dl_state["done"] = True
                _flare_dl_state["status"] = "error"
            except Exception as e:
                _flare_dl_state["error"] = f"下载失败: {str(e)}"
                _flare_dl_state["done"] = True
                _flare_dl_state["status"] = "error"

        threading.Thread(target=_do_download, daemon=True).start()
        return {"success": True, "status": "downloading", "message": "开始下载 FlareSolverr ...", "install_path": install_path}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@router.get("/flare-download-progress")
async def flare_download_progress():
    global _flare_dl_state
    return {
        "downloaded": _flare_dl_state["downloaded"],
        "total": _flare_dl_state["total"],
        "done": _flare_dl_state["done"],
        "error": _flare_dl_state["error"],
        "status": _flare_dl_state["status"],
    }


@router.post("/install-flare-complete")
async def install_flare_complete():
    """Called by frontend after download done to finalize installation.
    Extraction already happened in the download thread — just find the exe."""
    global _flare_dl_state
    try:
        install_path = _flare_last_install_path or _flare_dl_state.get("install_path", "")
        if not install_path or not os.path.isdir(install_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            install_path = os.path.join(base_dir, "tools", "flaresolverr")

        # Find the exe (walk the install dir)
        exe_path = ""
        for root, dirs, files in os.walk(install_path):
            for f in files:
                if f.lower() == "flaresolverr.exe":
                    exe_path = os.path.join(root, f)
                    break
            if exe_path:
                break

        if exe_path:
            _flare_dl_state = {"downloaded": 0, "total": 0, "done": True, "error": "", "status": "done"}
            # Auto-start FlareSolverr after successful installation
            try:
                from engine.flaresolverr import check_flaresolverr, start_flaresolverr
                config = get_config()
                # Save exe path to config so re-detection works
                update_config({"flaresolverr_path": os.path.dirname(os.path.abspath(exe_path))})
                already_running = await check_flaresolverr(config)
                started = already_running
                if not already_running:
                    started = await start_flaresolverr(config)
                return {"success": True, "path": os.path.abspath(exe_path), "started": started, "exe_path": exe_path}
            except Exception:
                return {"success": True, "path": os.path.abspath(exe_path), "started": False, "exe_path": exe_path}

        # Check if extraction is still pending
        zip_path = os.path.join(install_path, "flaresolverr.zip")
        if os.path.exists(zip_path):
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(install_path)
                os.remove(zip_path)
                for root, dirs, files in os.walk(install_path):
                    for f in files:
                        if f.lower() == "flaresolverr.exe":
                            return {"success": True, "path": os.path.abspath(os.path.join(root, f))}
            except Exception as e:
                return {"success": False, "error": f"解压失败: {e}"}

        return {"success": False, "error": "未找到 flaresolverr.exe，请重试"}
    except Exception as e:
        return {"success": False, "error": f"安装确认异常: {e}"}


@router.post("/check-flare")
async def check_flare(body: Optional[Dict[str, Any]] = None):
    try:
        from engine.flaresolverr import check_flaresolverr, find_flaresolverr_exe
        from config import get_config, update_config
        config = get_config()
        running = await check_flaresolverr(config)

        # If a manual path is provided, save it to config and prioritize it
        manual_path = (body or {}).get("manual_path", "")
        if manual_path:
            import shutil as _shutil
            # Check if the path contains flaresolverr.exe directly or in subdirs
            for check in [
                os.path.join(manual_path, "flaresolverr.exe"),
                os.path.join(manual_path, "flaresolverr", "flaresolverr.exe"),
            ]:
                if os.path.exists(check):
                    update_config({"flaresolverr_path": os.path.dirname(os.path.abspath(check))})
                    return {"available": running, "installed": True, "exe_path": os.path.abspath(check)}

        exe_path = find_flaresolverr_exe(config)
        return {"available": running, "installed": bool(exe_path), "exe_path": exe_path or ""}
    except Exception as e:
        return {"available": False, "installed": False, "exe_path": "", "error": str(e)}


@router.post("/start-flare")
async def start_flare():
    try:
        from engine.flaresolverr import start_flaresolverr
        success, message = await start_flaresolverr(get_config())
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/stop-flare")
async def stop_flare():
    try:
        from engine.flaresolverr import stop_flaresolverr
        stop_flaresolverr()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


class ConfigureFlarePathRequest(BaseModel):
    path: str


@router.post("/configure-flare-path")
async def configure_flare_path(body: ConfigureFlarePathRequest):
    """Configure a custom FlareSolverr path by updating config."""
    try:
        path = body.path.strip()
        if not path:
            return {"success": False, "error": "路径不能为空"}
        exe_path = os.path.join(path, "flaresolverr.exe")
        if not os.path.exists(exe_path):
            return {"success": False, "error": f"未找到 flaresolverr.exe，路径: {path}"}
        update_config({"flaresolverr_path": path})
        return {"success": True, "path": os.path.abspath(exe_path)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _parse_version(tag: str) -> Tuple[int, ...]:
    v = tag.lstrip("v")
    try:
        return tuple(int(p) for p in v.split(".") if p.isdigit())
    except (ValueError, AttributeError):
        return (0,)


def _check_github_update():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "book-downloader-updater"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        tag_name = data.get("tag_name", "")
        latest = _parse_version(tag_name)
        current = _parse_version(VERSION)
        html_url = data.get("html_url", "")
        body = data.get("body", "")
        download_url = ""
        setup_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            dl = asset.get("browser_download_url", "")
            if name.endswith(".exe") and "setup" in name.lower():
                setup_url = dl
            elif not download_url:
                download_url = dl
        if latest > current:
            return {
                "current": VERSION,
                "latest": tag_name.lstrip("v"),
                "has_update": True,
                "download_url": download_url or html_url,
                "setup_url": setup_url,
                "body": body,
                "published_at": data.get("published_at", ""),
            }
        return {"has_update": False, "current": VERSION}
    except Exception:
        return {"has_update": False, "error": "unable to check", "current": VERSION}


@router.get("/check-update")
async def check_update():
    return _check_github_update()


_update_download_progress = {"downloaded": 0, "total": 0, "done": False, "error": "", "dst": ""}


def _report_progress(block_count, block_size, total_size):
    _update_download_progress["downloaded"] = min(block_count * block_size, total_size)
    _update_download_progress["total"] = total_size


@router.get("/download-update")
async def download_update():
    global _update_download_progress
    _update_download_progress = {"downloaded": 0, "total": 0, "done": False, "error": "", "dst": ""}

    def _check_and_start():
        nonlocal_error = [""]
        try:
            info = _check_github_update()
            if not info.get("has_update"):
                nonlocal_error[0] = "已是最新版本"
                return
            dl_url = info.get("setup_url") or info.get("download_url")
            if not dl_url:
                nonlocal_error[0] = "无下载链接"
                return
            dst = os.path.join(tempfile.gettempdir(), "book-downloader-update", os.path.basename(dl_url.split("?")[0]))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _update_download_progress["dst"] = dst
            _do_download(dl_url, dst)
        except Exception as e:
            _update_download_progress["error"] = str(e)
            _update_download_progress["done"] = True

    threading.Thread(target=_check_and_start, daemon=True).start()
    return {"ok": True, "message": "download started"}


def _do_download(url: str, dst: str):
    global _update_download_progress
    try:
        urllib.request.urlretrieve(url, dst, _report_progress)

        # Verify: check if it's an exe at least 10MB
        if os.path.getsize(dst) < 10 * 1024 * 1024:
            _update_download_progress["error"] = "下载文件异常"
            _update_download_progress["done"] = True
            return
        _update_download_progress["done"] = True
    except Exception as e:
        _update_download_progress["error"] = str(e)
        _update_download_progress["done"] = True


@router.get("/download-progress")
async def download_progress():
    return {
        "downloaded": _update_download_progress["downloaded"],
        "total": _update_download_progress["total"],
        "done": _update_download_progress["done"],
        "error": _update_download_progress["error"],
    }


@router.post("/install-update")
async def install_update():
    try:
        import sys
        exe_path = sys.executable
        new_exe = _update_download_progress.get("dst", "")
        if not new_exe or not os.path.exists(new_exe):
            return {"ok": False, "error": "未找到下载的更新文件"}

        bat_path = os.path.join(tempfile.gettempdir(), "book-downloader-update", "update.bat")
        with open(bat_path, "w") as f:
            f.write("@echo off\r\n")
            f.write("timeout /t 2 /nobreak >nul\r\n")
            # If it's a setup exe, run it silently
            if "setup" in new_exe.lower():
                f.write(f'start "" /wait "{new_exe}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART\r\n')
            else:
                f.write(f'copy /y "{new_exe}" "{exe_path}"\r\n')
                f.write(f'start "" "{exe_path}"\r\n')
            f.write("del \"%~f0\"\r\n")

        subprocess.Popen(["cmd", "/c", bat_path], shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
