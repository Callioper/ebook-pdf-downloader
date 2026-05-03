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


@router.get("/browse-folder")
async def browse_folder():
    if os.name != "nt":
        return {"path": "", "error": "not supported on this platform"}
    for method in ["powershell", "vbs"]:
        try:
            path = ""
            if method == "powershell":
                ps_script = os.path.join(tempfile.gettempdir(), "bdf_browse.ps1")
                with open(ps_script, "w") as f:
                    f.write(
                        'Add-Type -AssemblyName System.Windows.Forms\n'
                        '$f = New-Object System.Windows.Forms.FolderBrowserDialog\n'
                        '$f.Description = "Select database folder containing DX_*.db files"\n'
                        '$f.ShowNewFolderButton = $false\n'
                        '$r = $f.ShowDialog()\n'
                        'if ($r -eq "OK") { $f.SelectedPath } else { "" }\n'
                    )
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-WindowStyle", "Normal", "-File", ps_script],
                    capture_output=True, text=True, timeout=120,
                )
                path = proc.stdout.strip()
                try:
                    os.remove(ps_script)
                except Exception:
                    pass
            else:
                vbs_path = os.path.join(tempfile.gettempdir(), "bdf_browse.vbs")
                with open(vbs_path, "w") as f:
                    f.write(
                        'Set objShell = CreateObject("Shell.Application")\n'
                        'Set objFolder = objShell.BrowseForFolder(0, "Select database folder", &H51, 0)\n'
                        'If Not objFolder Is Nothing Then\n'
                        '  If Not IsNull(objFolder.Self) Then\n'
                        '    WScript.Echo objFolder.Self.Path\n'
                        '  End If\n'
                        'End If\n'
                    )
                proc = subprocess.run(
                    ["cscript", "//Nologo", vbs_path],
                    capture_output=True, text=True, timeout=120,
                )
                path = proc.stdout.strip()
                try:
                    os.remove(vbs_path)
                except Exception:
                    pass
            if path:
                return {"path": path}
        except Exception as e:
            if method == "vbs":
                return {"path": "", "error": str(e)}
    return {"path": "", "error": "unable to open folder dialog"}


@router.get("/detect-paths")
async def detect_paths():
    paths = detect_database_paths()
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
        return {"ok": True, "message": "Proxy is working"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.post("/check-proxy-sources")
async def check_proxy_sources(body: ProxyRequest):
    proxy_url = body.http_proxy or get_config().get("http_proxy", "")
    results = {}
    details = {}
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        import requests as curl_requests
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
    for name, url in targets:
        try:
            if proxy_url:
                proxies = {"http": proxy_url, "https": proxy_url}
                resp = curl_requests.get(url, timeout=8, headers=headers, proxies=proxies)
            else:
                resp = curl_requests.get(url, timeout=8, headers=headers)
            results[name] = resp.status_code == 200
            details[name] = "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        except Exception as e:
            results[name] = False
            details[name] = str(e)[:200]
    return {"ok": True, "results": results, "details": details}


@router.post("/zlib-fetch-tokens")
async def zlib_fetch_tokens(body: ZLibFetchTokensRequest):
    try:
        from engine.zlib_downloader import ZLibDownloader
        config = get_config()
        dl = ZLibDownloader(config)
        result = await dl.zlib_login(body.email, body.password)
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
                return {"ok": True, "engine": "paddleocr"}
            except ImportError:
                pass
        elif engine == "easyocr":
            try:
                import easyocr
                return {"ok": True, "engine": "easyocr"}
            except ImportError:
                pass
        return {"ok": False, "engine": engine, "message": f"{engine} not found"}
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
                ["pip", "install", "paddlepaddle", "paddleocr"],
                capture_output=True, text=True, timeout=300
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:]}
        elif engine == "easyocr":
            result = subprocess.run(
                ["pip", "install", "easyocr"],
                capture_output=True, text=True, timeout=300
            )
            return {"ok": result.returncode == 0, "message": result.stdout.strip()[-500:]}
        else:
            return {"ok": False, "message": f"Unknown engine: {engine}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.post("/install-flare")
async def install_flare(body: InstallFlareRequest):
    try:
        install_path = body.install_path
        if not install_path:
            install_path = os.path.join(tempfile.gettempdir(), "book-downloader", "flaresolverr")

        zip_path = os.path.join(install_path, "flaresolverr.zip")
        os.makedirs(install_path, exist_ok=True)

        try:
            urllib.request.urlretrieve(FLARE_INSTALL_URL, zip_path)
        except urllib.error.HTTPError as e:
            return {"success": False, "error": f"下载失败 (HTTP {e.code}): GitHub 返回 {e.code} 错误，请检查网络或手动安装"}
        except urllib.error.URLError as e:
            return {"success": False, "error": f"下载失败 (网络错误): {e.reason}，请检查网络连接或使用代理后重试"}
        except Exception as e:
            return {"success": False, "error": f"下载失败: {str(e) or '未知下载错误'}"}

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(install_path)
        except zipfile.BadZipFile:
            return {"success": False, "error": "下载文件损坏 (非有效 ZIP)，请删除临时文件后重试"}
        except Exception as e:
            return {"success": False, "error": f"解压失败: {str(e) or '未知解压错误'}"}

        try:
            os.remove(zip_path)
        except Exception:
            pass

        exe_path = os.path.join(install_path, "flaresolverr.exe")
        if not os.path.exists(exe_path):
            for root, dirs, files in os.walk(install_path):
                for f in files:
                    if f.lower() == "flaresolverr.exe":
                        exe_path = os.path.join(root, f)
                        break

        if os.path.exists(exe_path):
            return {"success": True, "path": os.path.abspath(exe_path)}
        return {"success": False, "error": "解压后未找到 flaresolverr.exe，请确认压缩包结构是否正确"}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": f"安装异常: {str(e) or '未知错误'}"}


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
