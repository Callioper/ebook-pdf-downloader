import os
import sqlite3
import shutil
import sys
from pathlib import Path
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

        return {
            "books": deduped,
            "total": total,
            "totalRecords": total,
            "totalPages": max(1, (total + page_size - 1) // page_size),
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


def detect_database_paths() -> List[Dict[str, Any]]:
    """Find directories containing DX_2.0-5.0.db or DX_6.0.db files."""
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
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

    def scan_dir(base: Path, max_depth: int = 2):
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
                            scan_dir(child, max_depth - 1)
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass

    # Known project paths
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

    # Common directory names to scan under drives / user dirs
    known_names = ["BookDownloader", "EbookDatabase", "EBook", "ebook", "books", "ebooks",
                   "LibGen", "libgen", "pdf", "PDF", "data", "db", "database"]

    # Scan Windows drive roots for known directories
    if os.name == "nt":
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":  # skip A: and B: (floppy)
            try:
                root = Path(f"{drive}:\\")
                if not os.path.exists(str(root)):
                    continue
                for name in known_names:
                    check_path(root / name)
            except (PermissionError, OSError):
                continue

    # Scan user home subdirs
    for sub in ["Downloads", "Documents", "Desktop"]:
        p = home / sub
        if p.exists():
            check_path(p)
            for name in known_names:
                check_path(p / name)
    # Deeper scan of Downloads (common place for downloaded DBs)
    downloads = home / "Downloads"
    if downloads.exists():
        try:
            for child in downloads.iterdir():
                if child.is_dir():
                    check_path(child)
        except (PermissionError, OSError):
            pass

    candidates.sort(key=lambda c: len(c.get("dbs", [])), reverse=True)
    return candidates if candidates else []