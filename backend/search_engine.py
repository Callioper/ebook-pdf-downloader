# -*- coding: utf-8 -*-
# ==== search_engine.py ====
# 职责：SQLite电子书数据库搜索引擎，支持多数据库查询和路径检测
# 入口函数：SearchEngine.search(), detect_database_paths()
# 依赖：无
# 注意：使用本地缓存避免UNC路径锁定，支持DX_2.0-5.0和DX_6.0数据库

import os
import sqlite3
import shutil
import sys
from pathlib import Path
import time as _time
from typing import Any, Dict, List


class SearchEngine:
    """SQLite ebook database search engine."""

    def __init__(self):
        self._db_dir = ""
        self._dbs = {}

    def set_db_dir(self, path: str):
        self._db_dir = path

    def _get_db_dir(self) -> str:
        if self._db_dir and os.path.isdir(self._db_dir):
            return self._db_dir
        candidates = [
            str(Path(__file__).resolve().parent / "data"),
            str(Path.home() / "EbookDatabase" / "instance"),
        ]
        for p in candidates:
            try:
                if os.path.isdir(p):
                    return p
            except Exception:
                continue
        return ""

    def _connect(self, db_name: str):
        db_dir = self._get_db_dir()
        if not db_dir:
            return None
        src = os.path.join(db_dir, db_name)
        if not os.path.exists(src):
            return None
        # Copy to local cache to avoid UNC locking
        cache_dir = os.path.join(os.environ.get("TEMP", os.path.dirname(__file__)), "bdw_db_cache")
        os.makedirs(cache_dir, exist_ok=True)
        local = os.path.join(cache_dir, db_name)
        if not os.path.exists(local) or os.path.getsize(local) == 0:
            shutil.copy2(src, local)
        try:
            conn = sqlite3.connect(local, timeout=5, check_same_thread=False)
            conn.execute("PRAGMA query_only=ON")
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            return None

    def search(self, field: str = "title", query: str = "", page: int = 1, page_size: int = 20,
               fuzzy: bool = True, **kwargs) -> Dict[str, Any]:
        field_map = {"title": "title", "author": "author", "publisher": "publisher",
                     "isbn": "ISBN", "sscode": "SS_code"}
        col = field_map.get(field, "title")
        pattern = "%" + query.replace("%", "%%") + "%"

        all_books = []
        total = 0
        for db_name in ["DX_2.0-5.0.db", "DX_6.0.db"]:
            conn = self._connect(db_name)
            if not conn:
                continue
            try:
                c = conn.execute(f"SELECT count(*) FROM books WHERE {col} LIKE ?", (pattern,))
                total += c.fetchone()[0]
                offset = (page - 1) * page_size
                remaining = page_size - len(all_books)
                if remaining > 0:
                    c = conn.execute(
                        f"SELECT * FROM books WHERE {col} LIKE ? ORDER BY id LIMIT ? OFFSET ?",
                        (pattern, remaining, offset),
                    )
                    for r in c.fetchall():
                        book = dict(r)
                        if "ISBN" in book:
                            book["isbn"] = book.pop("ISBN")
                        if "SS_code" in book:
                            book["ss_code"] = book.pop("SS_code")
                        book["source"] = db_name.replace(".db", "")
                        all_books.append(book)
            except Exception:
                pass
            finally:
                conn.close()

        # Deduplicate
        seen = set()
        deduped = []
        for b in all_books:
            key = (b.get("isbn", ""), b.get("ss_code", ""))
            if key not in seen or not key[0]:
                seen.add(key)
                deduped.append(b)

        # Re-count after dedup so total matches actual displayed count
        real_total = len(deduped)

        return {
            "books": deduped,
            "total": real_total,
            "totalRecords": real_total,
            "totalPages": max(1, (real_total + page_size - 1) // page_size),
        }

    def available_dbs(self) -> List[str]:
        db_dir = self._get_db_dir()
        if not db_dir:
            return []
        found = []
        for f in ["DX_2.0-5.0.db", "DX_6.0.db"]:
            if os.path.exists(os.path.join(db_dir, f)):
                found.append(f.replace(".db", ""))
        return found

    def is_connected(self) -> bool:
        return len(self.available_dbs()) > 0


search_engine = SearchEngine()


def detect_database_paths(timeout: float = 30.0) -> List[Dict[str, Any]]:
    """Find directories containing DX_2.0-5.0.db or DX_6.0.db files."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    deadline = _time.time() + timeout
    try:
        home = Path.home()
    except Exception:
        home = Path("C:\\Users")
    target_files = ["DX_2.0-5.0.db", "DX_6.0.db"]

    def check_path(p: Path):
        key = str(p.resolve())
        if key in seen:
            return
        seen.add(key)
        try:
            if p.exists() and p.is_dir():
                dbs = [f for f in target_files if (p / f).exists()]
                if dbs:
                    candidates.append({"path": str(p), "dbs": dbs, "exists": True})
        except (PermissionError, OSError):
            pass

    def _safe_scan_dir(base: Path, max_depth: int = 3):
        try:
            if not base.exists() or not base.is_dir():
                return
            check_path(base)
            if max_depth <= 0:
                return
            for child in base.iterdir():
                try:
                    if child.is_dir():
                        check_path(child)
                        if max_depth > 1:
                            _safe_scan_dir(child, max_depth - 1)
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass

    # === Priority paths (fast check) ===
    for p in [
        Path(__file__).resolve().parent / "data",
        home / "EbookDatabase" / "instance",
        home / ".book-downloader" / "data",
        Path.cwd(),
        Path(sys.executable).parent if hasattr(sys, 'executable') else None,
    ]:
        if p is None:
            continue
        check_path(p)

    # === Common directory names ===
    known_names = [
        "ebook-pdf-downloader", "book-downloader", "EbookDatabase", "EBook", "ebook", "ebooks",
        "books", "book", "LibGen", "libgen", "pdf", "PDF", "data", "db", "database",
        "instance", "ebook_database", "eBook Database", "ebook_db", "DB",
        "calibre", "Calibre", "Calibre 书库",
    ]

    # === Direct scan all drives for DB files at root level ===
    if os.name == "nt":
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            try:
                root = Path(f"{drive}:\\")
                if not os.path.exists(str(root)):
                    continue
                for db_name in target_files:
                    db_path = root / db_name
                    if db_path.exists():
                        candidates.append({"path": str(root), "dbs": [db_name], "exists": True})
                        break
            except (PermissionError, OSError):
                continue

    # === Scan drive roots for known directory names (depth 1 into match) ===
    if os.name == "nt":
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            try:
                root = Path(f"{drive}:\\")
                if not os.path.exists(str(root)):
                    continue
                for name in known_names:
                    p = root / name
                    if p.exists() and p.is_dir():
                        _safe_scan_dir(p, max_depth=1)
            except (PermissionError, OSError):
                continue

    # === Scan all drive root subdirs (depth 2: subdir -> known_name -> db) ===
    if os.name == "nt":
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            try:
                root = Path(f"{drive}:\\")
                if not os.path.exists(str(root)):
                    continue
                for child in root.iterdir():
                    try:
                        if child.is_dir():
                            for name in known_names:
                                p = child / name
                                if p.exists() and p.is_dir():
                                    _safe_scan_dir(p, max_depth=1)
                    except (PermissionError, OSError):
                        pass
            except (PermissionError, OSError):
                continue

    # === Scan user home subdirs (English + Chinese) at depth 2 ===
    for sub in ["Downloads", "下载", "Documents", "文档", "Desktop", "桌面"]:
        p = home / sub
        if not p.exists():
            continue
        _safe_scan_dir(p, max_depth=2)

    # === Scan common Windows special folders ===
    for env_var in ["USERPROFILE", "APPDATA", "LOCALAPPDATA", "OneDrive", "OneDriveCommercial"]:
        val = os.environ.get(env_var, "")
        if val and os.path.isdir(val):
            p = Path(val)
            check_path(p)
            for name in known_names:
                check_path(p / name)
            _safe_scan_dir(p, max_depth=1)

    # === Scan Program Files directories ===
    for prog_dir in [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                     os.environ.get("ProgramW6432", "")]:
        if not prog_dir or not os.path.isdir(prog_dir):
            continue
        p = Path(prog_dir)
        for name in known_names:
            check_path(p / name)

    # === Scan siblings of project root ===
    try:
        project_root = Path(__file__).resolve().parent.parent
        check_path(project_root / "data")
        for child in project_root.iterdir():
            if child.is_dir() and child.name not in ("backend", "frontend", ".git", "node_modules", "venv"):
                check_path(child)
                for name in known_names:
                    check_path(child / name)
    except Exception:
        pass

    # === Deep recursive scan if no results yet (os.walk on all drives) ===
    if not candidates and os.name == "nt":
        _skip_dirs = {
            "Windows", "Program Files", "Program Files (x86)", "ProgramData",
            "Windows.old", "$RECYCLE.BIN", "System Volume Information",
            "node_modules", "__pycache__", ".git", "venv", ".venv", ".idea",
            "Recovery", "Boot", "EFI", "MSOCache", "PerfLogs",
        }
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            if _time.time() > deadline:
                break
            walk_root = Path(f"{drive}:\\")
            if not walk_root.exists():
                continue
            try:
                for dirpath_str, dirnames, filenames in os.walk(str(walk_root), followlinks=False):
                    if _time.time() > deadline:
                        break
                    dirnames[:] = [d for d in dirnames if d not in _skip_dirs]
                    depth = len(dirpath_str) - len(str(walk_root)) - dirpath_str.count(os.sep)
                    if depth > 8:
                        dirnames.clear()
                        continue
                    has_db = any(tf in filenames for tf in target_files)
                    if has_db:
                        dirpath = Path(dirpath_str)
                        dbs = [f for f in target_files if (dirpath / f).exists()]
                        if dbs:
                            candidates.append({"path": dirpath_str, "dbs": dbs, "exists": True})
                            break
                    if len(candidates) >= 5:
                        break
            except (PermissionError, OSError):
                continue
            if len(candidates) >= 5:
                break

    candidates.sort(key=lambda c: len(c.get("dbs", [])), reverse=True)
    return candidates if candidates else []