# ==== flaresolverr.py ====
# 职责：FlareSolverr进程管理和CloudFlare绕过下载
# 入口函数：start_flaresolverr(), stop_flaresolverr(), check_flaresolverr(), download_via_flaresolverr()
# 依赖：无
# 注意：管理全局进程实例，支持自动查找和启动FlareSolverr

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)
_flare_process: Optional[subprocess.Popen] = None


def find_flaresolverr_exe(config: Dict[str, Any]) -> Optional[str]:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cfg_path = config.get("flaresolverr_path", "")

    # Build search path list: all plausible locations
    search_paths = []

    # 1. Config path: check both the dir itself (if it IS the exe dir) and parent paths
    if cfg_path:
        for sub in ["", "flaresolverr"]:
            p = os.path.join(cfg_path, sub, "flaresolverr.exe")
            if p not in search_paths:
                search_paths.append(p)
        if cfg_path.lower().endswith(".exe"):
            search_paths.insert(0, cfg_path)

    # 2. Default install paths
    search_paths += [
        os.path.join(base_dir, "tools", "flaresolverr", "flaresolverr", "flaresolverr.exe"),
        os.path.join(base_dir, "tools", "flaresolverr", "flaresolverr.exe"),
        os.path.join(tempfile.gettempdir(), "book-downloader", "flaresolverr", "flaresolverr", "flaresolverr.exe"),
        os.path.join(tempfile.gettempdir(), "book-downloader", "flaresolverr", "flaresolverr.exe"),
    ]

    for path in search_paths:
        if path and os.path.exists(path):
            return os.path.abspath(path)

    # Walk search directories (like database smart detection)
    walk_dirs = []

    # Config path parent (user's install dir)
    if cfg_path:
        parent = os.path.dirname(cfg_path)
        if os.path.isdir(parent):
            walk_dirs.append(parent)
        if os.path.isdir(cfg_path):
            walk_dirs.append(cfg_path)

    # Common locations
    walk_dirs += [
        os.path.join(base_dir, "tools", "flaresolverr"),
        os.path.join(tempfile.gettempdir(), "book-downloader", "flaresolverr"),
    ]
    # Project root
    if os.path.isdir(base_dir):
        walk_dirs.append(base_dir)

    # Drive-level scan: for each drive, scan first-level dirs and subdirs named 'flaresolverr'
    if os.name == "nt":
        known_names = {"flaresolverr", "FlareSolverr", "tools", "apps"}
        for drive_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_root = f"{drive_letter}:\\"
            if not os.path.isdir(drive_root):
                continue
            # Scan first-level directories on this drive
            try:
                for entry in os.listdir(drive_root):
                    child = os.path.join(drive_root, entry)
                    if not os.path.isdir(child) or entry.startswith("."):
                        continue
                    # Quick check: known dir names at first level
                    if entry.lower() in known_names:
                        walk_dirs.append(child)
                    # Always check for 'flaresolverr' subdir inside any first-level dir
                    flaresolverr_sub = os.path.join(child, "flaresolverr")
                    if os.path.isdir(flaresolverr_sub):
                        walk_dirs.append(flaresolverr_sub)
                    # Also check child for flaresolverr.exe directly (depth 1 quick scan)
                    flaresolverr_exe = os.path.join(child, "flaresolverr.exe")
                    if os.path.exists(flaresolverr_exe):
                        try:
                            from config import update_config
                            update_config({"flaresolverr_path": os.path.dirname(os.path.abspath(flaresolverr_exe))})
                        except Exception:
                            pass
                        return os.path.abspath(flaresolverr_exe)
            except (PermissionError, OSError):
                continue

    seen = set()
    for walk_base in walk_dirs:
        if not walk_base or walk_base in seen:
            continue
        seen.add(walk_base)
        try:
            for root, dirs, files in os.walk(walk_base):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", "__pycache__", "node_modules")]
                for f in files:
                    if f.lower() == "flaresolverr.exe":
                        # Save to config so next lookups are instant
                        try:
                            from config import update_config
                            update_config({"flaresolverr_path": os.path.dirname(os.path.abspath(os.path.join(root, f)))})
                        except Exception:
                            pass
                        return os.path.abspath(os.path.join(root, f))
        except (PermissionError, OSError):
            continue

    return None


async def check_flaresolverr(config: Dict[str, Any]) -> bool:
    # Try multiple health check endpoints
    for endpoint in ["/v1", "/health"]:
        try:
            r = requests.get(
                f"http://localhost:8191{endpoint}",
                timeout=5,
            )
            if r.status_code == 200:
                return True
            # Also accept any OK status from /v1
            if endpoint == "/v1":
                try:
                    data = r.json()
                    if data.get("status") == "ok":
                        return True
                except Exception:
                    pass
        except requests.ConnectionError as e:
            logger.warning(f"FlareSolverr check ({endpoint}) connection failed: {e}")
        except Exception as e:
            logger.warning(f"FlareSolverr check ({endpoint}) failed: {e}")
    return False


async def start_flaresolverr(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Returns (success, error_message)."""
    global _flare_process
    if await check_flaresolverr(config):
        return (True, "already running")

    exe_path = find_flaresolverr_exe(config)
    if not exe_path:
        return (False, "未找到 flaresolverr.exe，请先安装")

    # Step 1: Quick sanity check — can the exe start at all
    try:
        quick_test = subprocess.run([exe_path, "--version"], capture_output=True, text=True, timeout=10)
        if quick_test.returncode != 0:
            err = (quick_test.stderr or quick_test.stdout or "无输出")[:200]
            return (False, f"flaresolverr.exe 无法运行: {err}")
    except FileNotFoundError:
        return (False, f"flaresolverr.exe 不存在: {exe_path}")
    except Exception as e:
        return (False, f"flaresolverr.exe 测试失败: {str(e)}")

    try:
        cwd = os.path.dirname(exe_path)
        # Some FlareSolverr builds need their own directory as cwd to find bundled files
        if not cwd:
            cwd = os.getcwd()
        CREATE_NO_WINDOW = 0x08000000
        _flare_process = subprocess.Popen(
            [exe_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=cwd,
            creationflags=CREATE_NO_WINDOW,
        )
        # Read stderr in background to detect early crashes
        stderr_lines = []
        async def _read_stderr():
            try:
                for line in iter(_flare_process.stderr.readline, b""):
                    stderr_lines.append(line.decode("utf-8", errors="replace"))
            except Exception:
                pass
        asyncio.create_task(_read_stderr())
        # Wait up to 30 seconds for FlareSolverr to start
        for _ in range(30):
            await asyncio.sleep(1)
            # If process already exited, it crashed
            if _flare_process.poll() is not None:
                err_text = "".join(stderr_lines)[:500]
                return (False, f"FlareSolverr 进程已退出 (exit code {_flare_process.returncode})。错误: {err_text or '无错误输出'}")
            if await check_flaresolverr(config):
                return (True, "started")
        # Timeout — get accumulated stderr
        err_text = "".join(stderr_lines)[:500]
        try:
            _flare_process.terminate()
        except Exception:
            try:
                _flare_process.kill()
            except Exception:
                pass
        _flare_process = None
        detail = f"启动超时(30s)，端口8191无响应"
        if err_text:
            detail += f"。错误输出: {err_text}"
        logger.warning(f"FlareSolverr start failed: {detail}")
        return (False, detail)
    except Exception as e:
        return (False, f"启动异常: {str(e)}")

    return (False, "未知错误")


def stop_flaresolverr():
    global _flare_process
    if _flare_process:
        try:
            _flare_process.terminate()
            _flare_process.wait(timeout=10)
        except Exception as e:
            logger.warning(f"Failed to terminate FlareSolverr during stop: {e}")
            try:
                _flare_process.kill()
            except Exception as e2:
                logger.warning(f"Failed to kill FlareSolverr during stop: {e2}")
        _flare_process = None


async def download_via_flaresolverr(
    base_url: str,
    book_id: str,
    output_dir: str,
    proxy: str = "",
) -> bool:
    proxies = {"http": proxy, "https": proxy} if proxy else None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    try:
        flare_url = "http://localhost:8191/v1"
        session = requests.Session()
        if proxies:
            session.proxies.update(proxies)

        payload = {
            "cmd": "request.get",
            "url": f"{base_url}/book/{book_id}",
            "maxTimeout": 60000,
            "returnOnlyCookies": False,
        }

        r = session.post(flare_url, json=payload, timeout=70)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "ok":
                content = data.get("solution", {}).get("response", "")
                if content:
                    index_path = os.path.join(output_dir, "index.html")
                    with open(index_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    return True

        direct_r = requests.get(
            f"{base_url}/book/{book_id}",
            headers=headers,
            timeout=30,
            proxies=proxies,
        )
        if direct_r.status_code == 200:
            index_path = os.path.join(output_dir, "index.html")
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(direct_r.text)
            return True

        return False
    except Exception as e:
        logger.error(f"Failed to download via FlareSolverr: {e}")
        return False


async def get_page_content(url: str, proxy: str = "") -> Optional[str]:
    flare_url = "http://localhost:8191/v1"

    try:
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 30000,
        }
        # IMPORTANT: no proxy for FlareSolverr localhost request
        r = requests.post(flare_url, json=payload, timeout=40)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "ok":
                return data.get("solution", {}).get("response", "")
    except Exception as e:
        logger.warning(f"FlareSolverr get_page_content failed: {e}")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        proxies = {"http": proxy, "https": proxy} if proxy else None
        r = requests.get(url, headers=headers, timeout=15, proxies=proxies)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.warning(f"Direct get_page_content failed: {e}")

    return None


async def get_flaresolverr_cookies(url: str, proxy: str = "") -> Optional[Dict[str, str]]:
    """
    Use FlareSolverr to visit a page and extract Cloudflare clearance cookies.
    Returns a dict of cookie name → value that can be used with requests.
    """
    session_name = f"aa_{int(time.time())}"
    flare_url = "http://localhost:8191/v1"

    try:
        # Create session
        requests.post(flare_url, json={
            "cmd": "sessions.create", "session": session_name,
        }, timeout=5)
    except Exception as e:
        logger.warning(f"FlareSolverr session create failed: {e}")
        return None

    try:
        payload = {
            "cmd": "request.get",
            "url": url,
            "session": session_name,
            "maxTimeout": 60000,
        }
        r = requests.post(flare_url, json=payload, timeout=70)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "ok":
                cookies = data.get("solution", {}).get("cookies", [])
                if cookies:
                    cookie_dict = {}
                    for c in cookies:
                        name = c.get("name", "")
                        value = c.get("value", "")
                        if name and value:
                            cookie_dict[name] = value
                    if cookie_dict:
                        logger.info(f"Extracted {len(cookie_dict)} cookies via FlareSolverr session")
                        return cookie_dict
        logger.warning(f"FlareSolverr session failed: {data.get('status', 'unknown')}")
    except Exception as e:
        logger.warning(f"FlareSolverr get_cookies failed: {e}")
    finally:
        try:
            requests.post(flare_url, json={
                "cmd": "sessions.destroy", "session": session_name,
            }, timeout=3)
        except Exception:
            pass

    return None


async def download_file_via_flaresolverr(
    download_url: str,
    output_path: str,
    proxy: str = "",
    referer: str = "",
) -> bool:
    """
    Download a binary file through FlareSolverr by:
    1. Visiting the URL via a FlareSolverr session (gets Cloudflare clearance)
    2. Extracting the cookies
    3. Re-downloading directly with those cookies
    """
    session_name = f"dl_{int(time.time())}"
    flare_url = "http://localhost:8191/v1"

    try:
        requests.post(flare_url, json={
            "cmd": "sessions.create", "session": session_name,
        }, timeout=5)
    except Exception as e:
        logger.warning(f"File download: session create failed: {e}")
        return False

    try:
        payload = {
            "cmd": "request.get",
            "url": download_url,
            "session": session_name,
            "maxTimeout": 120000,
        }
        if referer:
            payload["headers"] = {"Referer": referer}

        r = requests.post(flare_url, json=payload, timeout=130)
        if r.status_code == 200:
            data = r.json()
            solution = data.get("solution", {})
            # Extract cookies
            cookies = solution.get("cookies", [])
            cookie_dict = {}
            for c in cookies:
                name = c.get("name", "")
                value = c.get("value", "")
                if name and value:
                    cookie_dict[name] = value

            if cookie_dict:
                logger.info(f"Using {len(cookie_dict)} cookies for direct download")

            hdrs = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            if referer:
                hdrs["Referer"] = referer

            resp = requests.get(
                download_url,
                headers=hdrs,
                cookies=cookie_dict,
                timeout=60,
                allow_redirects=True,
                verify=False,
                stream=True,
            )

            if resp.status_code == 200 and len(resp.content) > 1024:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                logger.info(f"Downloaded {len(resp.content)} bytes to {output_path}")
                return True

            logger.warning(f"Direct download failed: HTTP {resp.status_code}, {len(resp.content)} bytes")
        else:
            logger.warning(f"FlareSolverr request failed: HTTP {r.status_code}")
    except Exception as e:
        logger.warning(f"File download via FlareSolverr failed: {e}")
    finally:
        try:
            requests.post(flare_url, json={
                "cmd": "sessions.destroy", "session": session_name,
            }, timeout=3)
        except Exception:
            pass

    return False
