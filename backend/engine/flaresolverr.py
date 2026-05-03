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
        # Also check the EXACT path if it looks like an exe path
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

    # Walk search directories
    walk_dirs = []
    # Config path parent (user's install dir)
    if cfg_path and os.path.isdir(os.path.dirname(cfg_path)):
        walk_dirs.append(os.path.dirname(cfg_path))
    # Config path itself
    if cfg_path and os.path.isdir(cfg_path):
        walk_dirs.append(cfg_path)
    # Common locations
    walk_dirs += [
        os.path.join(base_dir, "tools", "flaresolverr"),
        os.path.join(tempfile.gettempdir(), "book-downloader", "flaresolverr"),
    ]
    # Project root
    if os.path.isdir(base_dir):
        walk_dirs.append(base_dir)

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
                        return os.path.abspath(os.path.join(root, f))
        except (PermissionError, OSError):
            continue

    return None


async def check_flaresolverr(config: Dict[str, Any]) -> bool:
    proxy = config.get("http_proxy", "")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = requests.get(
            "http://localhost:8191/v1",
            timeout=5,
            proxies=proxies,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"FlareSolverr check failed: {e}")
        return False


async def start_flaresolverr(config: Dict[str, Any]) -> bool:
    global _flare_process
    if await check_flaresolverr(config):
        return True

    exe_path = find_flaresolverr_exe(config)
    if not exe_path:
        return False

    try:
        cwd = os.path.dirname(exe_path)
        # Use CREATE_NO_WINDOW to hide console window on Windows
        CREATE_NO_WINDOW = 0x08000000
        _flare_process = subprocess.Popen(
            [exe_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            creationflags=CREATE_NO_WINDOW,
        )
        # Wait up to 30 seconds for FlareSolverr to start
        for _ in range(30):
            await asyncio.sleep(1)
            if await check_flaresolverr(config):
                return True
        # If startup failed, kill the process
        try:
            _flare_process.terminate()
        except Exception as e:
            logger.warning(f"Failed to terminate FlareSolverr process: {e}")
            try:
                _flare_process.kill()
            except Exception as e2:
                logger.warning(f"Failed to kill FlareSolverr process: {e2}")
        _flare_process = None
        return False
    except Exception as e:
        logger.error(f"Failed to start FlareSolverr: {e}")
        return False


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
    proxies = {"http": proxy, "https": proxy} if proxy else None

    try:
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 30000,
        }
        r = requests.post(flare_url, json=payload, timeout=40, proxies=proxies)
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
        r = requests.get(url, headers=headers, timeout=15, proxies=proxies)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.warning(f"Direct get_page_content failed: {e}")

    return None
