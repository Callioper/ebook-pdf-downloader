import asyncio
import json
import os
import re
import subprocess
import tempfile
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Query, Request, UploadFile
from pydantic import BaseModel

from config import get_config, init_config, update_config
from search_engine import search_engine, detect_database_paths
from version import VERSION, GITHUB_REPO

router = APIRouter(prefix="/api/v1")

HTML_TAG_RE = re.compile(r'<[^>]+>')

FLARE_INSTALL_URL = "https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.4.6/flaresolverr_windows_x64.zip"

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


def _search_annas_archive(query: str, proxy: str = "") -> List[Dict[str, str]]:
    results = []
    encoded = urllib.parse.quote(query)
    url = f"https://annas-archive.gd/search?q={encoded}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            opener = urllib.request.build_opener(proxy_handler)
            resp = opener.open(req, timeout=6)
        else:
            resp = urllib.request.urlopen(req, timeout=6)
        html = resp.read().decode("utf-8", errors="ignore")
        seen = set()
        for m in re.finditer(r'href="/md5/([a-f0-9]{32})"', html):
            md5 = m.group(1)
            if md5 not in seen:
                seen.add(md5)
                results.append({"md5": md5, "md5_url": f"https://annas-archive.gd/md5/{md5}"})
    except Exception:
        pass
    return results


def _fetch_md5_page_info(md5: str, proxy: str = "") -> Dict[str, Any]:
    info: Dict[str, Any] = {"md5": md5, "source": "annas_archive"}
    url = f"https://annas-archive.gd/md5/{md5}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            opener = urllib.request.build_opener(proxy_handler)
            resp = opener.open(req, timeout=6)
        else:
            resp = urllib.request.urlopen(req, timeout=6)
        html = resp.read().decode("utf-8", errors="ignore")
        title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
        if title_m:
            raw_title = HTML_TAG_RE.sub('', title_m.group(1)).strip()
            info["title"] = raw_title
        for label, key in [
            (r'Author[s]?', "author"),
            (r'Language', "language"),
            (r'Format', "format"),
            (r'File size', "size"),
            (r'Year', "year"),
            (r'ISBN', "isbn"),
            (r'Publisher', "publisher"),
        ]:
            pattern = re.compile(rf'<[^>]*>{label}</[^>]*>\s*<[^>]*>(.*?)</[^>]*>', re.IGNORECASE | re.DOTALL)
            m = pattern.search(html)
            if m:
                val = HTML_TAG_RE.sub('', m.group(1)).strip()
                if val:
                    info[key] = val
        if "title" not in info:
            info["title"] = md5
    except Exception:
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
        for item in result.get("books", result.get("results", []))[:10]:
            books.append({
                "source": "zlibrary",
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                "isbn": item.get("isbn", ""),
                "publisher": item.get("publisher", ""),
                "year": str(item.get("year", "")),
                "language": item.get("language", ""),
                "format": item.get("extension", ""),
                "size": item.get("filesize", item.get("size", "")),
                "md5": item.get("md5", ""),
                "book_id": str(item.get("id", "")),
            })
        return books
    except Exception:
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
                    except Exception:
                        pass
            except Exception:
                pass
            return results

        def _run_zlib():
            try:
                return asyncio.new_event_loop().run_until_complete(_search_zlib(query, proxy))
            except Exception:
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
    return {"paths": paths}


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
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request("http://httpbin.org/ip", headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=6) as resp:
            resp.read()
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
            kwargs = {"timeout": 10, "headers": headers, "verify": False}
            if proxy:
                kwargs["proxies"] = {"http": proxy, "https": proxy}
            resp = _requests.get(url, **kwargs)
            return (resp.status_code in (200, 301, 302), "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}")
        except _requests.HTTPError as e:
            return (False, f"HTTP {e.response.status_code}")
        except Exception as e:
            return (False, str(e)[:100])

    for name, url in targets:
        ok, detail = _check_url(url, proxy_url if proxy_url else "")
        results[name] = ok
        details[name] = detail
    return {"ok": True, "results": results, "details": details}


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
                return {"ok": True, "engine": "tesseract", "version": result.stdout.split("\n")[0]}
        elif engine == "paddleocr":
            try:
                import paddleocr
                # Also check CLI
                result = subprocess.run(
                    [sys.executable, "-m", "paddleocr", "--version"],
                    capture_output=True, text=True, timeout=5
                )
                ver = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "已安装"
                return {"ok": True, "engine": "paddleocr", "version": ver}
            except ImportError:
                pass
        elif engine == "easyocr":
            try:
                import easyocr
                return {"ok": True, "engine": "easyocr"}
            except ImportError:
                pass
        return {"ok": False, "engine": engine, "message": f"{engine} not found"}
    except FileNotFoundError:
        return {"ok": False, "engine": engine, "message": f"{engine} 未安装或不在 PATH 中"}
    except Exception as e:
        return {"ok": False, "engine": engine, "message": str(e)}


@router.post("/install-ocr")
async def install_ocr(body: InstallOCRRequest):
    engine = body.engine
    try:
        if engine == "tesseract":
            return {"ok": False, "message": "请手动安装 Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki"}
        elif engine == "ocrmypdf":
            result = subprocess.run(
                ["pip", "install", "ocrmypdf"],
                capture_output=True, text=True, timeout=300
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:]}
        elif engine == "paddleocr":
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "paddlepaddle", "paddleocr", "--user"],
                capture_output=True, text=True, timeout=300
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:]}
        elif engine == "easyocr":
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "easyocr", "--user"],
                capture_output=True, text=True, timeout=300
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

                resp = _requests.get(FLARE_INSTALL_URL, stream=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
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
    """Called by frontend after download done to finalize installation."""
    global _flare_dl_state
    try:
        install_path = os.path.join(tempfile.gettempdir(), "book-downloader", "flaresolverr")
        zip_path = os.path.join(install_path, "flaresolverr.zip")

        if not os.path.exists(zip_path):
            # Already cleaned up or never downloaded
            exe_path = os.path.join(install_path, "flaresolverr.exe")
            if os.path.exists(exe_path):
                return {"success": True, "path": os.path.abspath(exe_path)}
            return {"success": False, "error": "未找到下载文件，请重新尝试自动下载或手动安装"}

        # The zip extracts to .../temp/book-downloader/flaresolverr/
        # which already contains flaresolverr/ subfolder from the zip structure
        extract_base = install_path

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_base)
        except zipfile.BadZipFile:
            return {"success": False, "error": "下载文件损坏，请删除临时文件后重试"}
        except Exception as e:
            return {"success": False, "error": f"解压失败: {str(e)}"}

        try:
            os.remove(zip_path)
        except Exception:
            pass

        # The zip structure has flaresolverr/ as the root folder inside the zip
        # So the exe ends up at: .../temp/book-downloader/flaresolverr/flaresolverr/flaresolverr.exe
        exe_path = os.path.join(extract_base, "flaresolverr", "flaresolverr.exe")
        if not os.path.exists(exe_path):
            for root, dirs, files in os.walk(install_path):
                for f in files:
                    if f.lower() == "flaresolverr.exe":
                        exe_path = os.path.join(root, f)
                        break

        if os.path.exists(exe_path):
            _flare_dl_state = {"downloaded": 0, "total": 0, "done": True, "error": "", "status": "done"}
            return {"success": True, "path": os.path.abspath(exe_path)}
        return {"success": False, "error": "解压后未找到 flaresolverr.exe"}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": f"安装异常: {str(e)}"}


@router.get("/check-flare")
async def check_flare():
    try:
        from engine.flaresolverr import check_flaresolverr, find_flaresolverr_exe
        running = check_flaresolverr()
        exe_path = find_flaresolverr_exe(get_config())
        return {"available": running, "installed": bool(exe_path), "exe_path": exe_path or ""}
    except Exception as e:
        return {"available": False, "installed": False, "exe_path": "", "error": str(e)}


@router.post("/start-flare")
async def start_flare():
    try:
        from engine.flaresolverr import start_flaresolverr
        ok = start_flaresolverr(get_config())
        return {"success": ok}
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
