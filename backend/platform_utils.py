# -*- coding: utf-8 -*-
"""Cross-platform abstraction for OS-specific operations."""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


# ── Config / App Data Directory ──

def get_app_data_dir(app_name: str = "ebook-pdf-downloader") -> Path:
    """Get the platform-appropriate config directory.
    In frozen mode: APPDATA / ~/Library / ~/.local/share
    In dev mode: project root directory."""
    if getattr(sys, 'frozen', False):
        return _get_frozen_data_dir(app_name)
    return _get_dev_data_dir(app_name)


def _get_dev_data_dir(app_name: str) -> Path:
    """Dev mode: return project root where config files live."""
    return Path(__file__).resolve().parent.parent


def _get_frozen_data_dir(app_name: str) -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("linux"):
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    else:  # Windows
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    conf_dir = base / app_name
    conf_dir.mkdir(parents=True, exist_ok=True)
    return conf_dir


def get_config_file() -> Path:
    if getattr(sys, 'frozen', False):
        return get_app_data_dir() / "config.json"
    return Path(__file__).resolve().parent.parent / "config.json"


def get_default_config_file() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "config.default.json"
    return Path(__file__).resolve().parent.parent / "config.default.json"


def get_tasks_file() -> Path:
    if getattr(sys, 'frozen', False):
        return get_app_data_dir() / "tasks.json"
    return Path(__file__).resolve().parent.parent / "tasks.json"


# ── File / Folder Opening ──

def open_file(path: str):
    """Open a file with the default system application."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", path])
    else:
        os.startfile(path)


def open_folder(path: str):
    """Open a folder in the system file manager."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", path])
    else:
        os.startfile(path)


# ── Browser Opening ──

def open_browser(url: str, app_mode: bool = False):
    """Open URL in browser. On Windows/macOS, try app mode first."""
    if sys.platform == "darwin":
        edge_apps = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        if app_mode:
            for browser in edge_apps:
                if os.path.exists(browser):
                    subprocess.Popen([browser, f"--app={url}", "--new-window"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
        subprocess.Popen(["open", url])
        return True
    elif sys.platform.startswith("linux"):
        if app_mode:
            for browser in ["google-chrome", "microsoft-edge", "chromium", "chromium-browser"]:
                found = shutil.which(browser)
                if found:
                    subprocess.Popen([found, f"--app={url}", "--new-window"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
        import webbrowser
        webbrowser.open(url)
        return True
    else:
        if app_mode:
            for edge_path in [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]:
                if os.path.exists(edge_path):
                    subprocess.Popen(
                        [edge_path, f"--app={url}", "--new-window", "--window-size=1200,800"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    return True
        import webbrowser
        webbrowser.open(url)
        return True


# ── Process Control (suspend/resume/kill) ──

def suspend_process(pid: int) -> bool:
    """Suspend a process by PID. Returns True if successful."""
    if sys.platform in ("darwin",) or sys.platform.startswith("linux"):
        try:
            os.kill(pid, signal.SIGSTOP)
            return True
        except Exception:
            return False
    else:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_SUSPEND_RESUME = 0x0800
            handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
            if not handle:
                kernel32.DebugActiveProcess(pid)
                handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
            if not handle:
                return False
            kernel32.DebugActiveProcess(pid)
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False


def resume_process(pid: int) -> bool:
    """Resume a suspended process by PID. Returns True if successful."""
    if sys.platform in ("darwin",) or sys.platform.startswith("linux"):
        try:
            os.kill(pid, signal.SIGCONT)
            return True
        except Exception:
            return False
    else:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_SUSPEND_RESUME = 0x0800
            handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
            if not handle:
                return False
            kernel32.DebugActiveProcessStop(pid)
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False


def kill_process_tree(pid: int):
    """Kill a process and its children."""
    if sys.platform in ("darwin",) or sys.platform.startswith("linux"):
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    else:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, shell=True)
        except Exception:
            pass


def setup_console_handler(callback):
    """Register a console close handler. No-op on macOS/Linux."""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint)
            def handler(ctrl_type):
                callback()
                return 0
            kernel32.SetConsoleCtrlHandler(handle(handler), 1)
        except Exception:
            pass


# ── Tesseract Detection ──

def find_tesseract() -> str:
    """Find tesseract executable path across platforms."""
    tesseract = shutil.which("tesseract")
    if tesseract:
        return tesseract

    if sys.platform == "darwin":
        candidates = [
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]
    elif sys.platform.startswith("linux"):
        candidates = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]
    else:
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def get_tessdata_dir() -> str:
    """Get tessdata directory path."""
    tess_path = find_tesseract()
    if tess_path:
        tess_dir = Path(tess_path).parent / "tessdata"
        if tess_dir.is_dir():
            return str(tess_dir)
    if sys.platform == "darwin":
        for d in ["/opt/homebrew/share/tessdata", "/usr/local/share/tessdata"]:
            if os.path.isdir(d):
                return d
    return ""


def configure_tesseract_env():
    """Add tesseract to PATH and set TESSDATA_PREFIX if needed."""
    tess_path = find_tesseract()
    if tess_path:
        tess_dir = str(Path(tess_path).parent)
        if tess_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = tess_dir + os.pathsep + os.environ.get("PATH", "")
    tessdata = get_tessdata_dir()
    if tessdata and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = tessdata


# ── Python Executable Detection ──

def find_python_executable(version: str = "") -> str:
    """Find a Python executable, optionally with a specific version."""
    if version:
        candidates = [f"python{version}", f"python{version.replace('.','')}"]
    else:
        candidates = ["python3", "python"]
    if sys.platform == "darwin" and version:
        candidates.append(f"/usr/local/opt/python@{version}/bin/python{version}")
        candidates.append(f"/opt/homebrew/opt/python@{version}/bin/python{version}")
    elif os.name == "nt" and version:
        short = version.replace(".", "")
        candidates.append(os.path.expandvars(rf"%LOCALAPPDATA%\Programs\Python\Python{short}\python.exe"))
        candidates.append(rf"C:\Python{short}\python.exe")
    for c in candidates:
        found = shutil.which(c)
        if found:
            return found
    return sys.executable


# ── Drive / File System Scanning ──

def get_search_roots() -> list:
    """Get root directories for recursive file scanning."""
    if sys.platform == "darwin":
        return [str(Path.home())]
    elif sys.platform.startswith("linux"):
        home = str(Path.home())
        roots = [home]
        for mp in ["/mnt", "/media"]:
            if os.path.isdir(mp):
                try:
                    roots.extend([os.path.join(mp, d) for d in os.listdir(mp)])
                except Exception:
                    pass
        return roots
    else:
        import string
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def get_download_dir() -> str:
    """Get platform default downloads directory."""
    return str(Path.home() / "Downloads")


def get_finished_dir() -> str:
    """Get platform default finished output directory."""
    return str(Path.home() / "Downloads" / "ebook-pdf-downloader" / "finished")
