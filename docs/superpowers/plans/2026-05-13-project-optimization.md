# Project Optimization — Startup + Dead Code + Search Speed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut startup time by removing eager heavy imports, eliminate 91 lines of dead code, and speed up search by caching DB connections.

**Architecture:** Four independent fixes: (1) delete `engine/__init__.py` eager imports of pikepdf/PyMuPDF/Pillow, (2) remove duplicate endpoint definitions in search.py, (3) lazy-load `bw_compress_pdf_blocking` inside its call site, (4) cache SQLite connections in `search_engine.py` instead of copying DB on every query.

**Tech Stack:** Python 3.11+, SQLite, PyMuPDF, FastAPI

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/__init__.py` | Remove eager heavy imports |
| `backend/api/search.py:1679-1721` | Delete duplicate endpoints |
| `backend/engine/pipeline.py:24` | Lazy import `bw_compress_pdf_blocking` |
| `backend/search_engine.py:42-61` | Cache SQLite connections, skip copy |

---

### Task 1: Remove eager heavy imports from `engine/__init__.py`

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\__init__.py`

**Impact:** HIGH — Eliminates pikepdf + Pillow + PyMuPDF load at startup.

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\engine\__init__.py`.

- [ ] **Step 2: Replace content**

Replace with empty or minimal init:

```python
# engine package — heavy modules imported lazily inside functions
```

(Remove all 4 import lines)

- [ ] **Step 3: Verify nothing breaks**

These modules are already imported directly where used:
- `pdf_bw_compress` → imported at `pipeline.py:24` (top-level) and inside the compress function
- `pdf_api_embed` → imported inside `pipeline.py` functions (lines 2578, 2586, etc.)
- `paddleocr_online_client` → imported inside `pipeline.py` functions
- `mineru_client` → imported inside `pipeline.py` functions

No code outside `engine/` imports from `engine/__init__.py` directly.

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/__init__.py
git commit -m "perf: remove eager heavy imports from engine/__init__ (pikepdf/PyMuPDF/Pillow)"
```

---

### Task 2: Delete duplicate endpoints in search.py

**Files:**
- Modify: `D:\opencode\book-downloader\backend\api\search.py:1679-1721`

**Impact:** HIGH — 91 lines of dead code. The second copies of `/check-mineru` and `/check-paddleocr-online` are never registered (first definition wins in FastAPI).

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\api\search.py` from line 1679 to 1721.

- [ ] **Step 2: Delete the dead code**

Delete lines 1679-1721 (both duplicate endpoint definitions):

```python
@router.post("/check-mineru")
async def check_mineru(req: Request):  # ← DELETE (line 1679-1699)
    ...

@router.post("/check-paddleocr-online")
async def check_paddleocr_online(req: Request):  # ← DELETE (line 1700-1721)
    ...
```

NOTE: Lines are approximate — read to find exact start and end. The `@router.get("/system-status")` at line 1724 should remain (keep it and everything after).

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\api\search.py
```

Work from: `D:\opencode\book-downloader`
Expected: silent success.

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/api/search.py
git commit -m "perf: remove duplicate /check-mineru and /check-paddleocr-online dead endpoints"
```

---

### Task 3: Lazy-load `bw_compress_pdf_blocking` in pipeline.py

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py:24`

**Impact:** HIGH — Delays pikepdf+Pillow load until PDF compression is actually needed (post-OCR step, not on task start).

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\engine\pipeline.py`. Find the top-level import:

```python
from backend.engine.pdf_bw_compress import bw_compress_pdf_blocking  # line 24
```

- [ ] **Step 2: Remove top-level import, add local import at call site**

Delete the top-level import at line 24.

Find where `bw_compress_pdf_blocking` is called (around line 2875 in `_run_ocrmypdf_with_progress` or the compress section). Add a local import inside that function:

```python
# Inside the function that calls bw_compress_pdf_blocking, before the call:
from backend.engine.pdf_bw_compress import bw_compress_pdf_blocking
```

- [ ] **Step 3: Also remove unused `import subprocess` from main.py**

Read `D:\opencode\book-downloader\backend\main.py`. Find and delete:
```python
import subprocess  # (line 9 — unused in this file)
```

- [ ] **Step 4: Verify syntax**

```bash
python -m py_compile backend\engine\pipeline.py
python -m py_compile backend\main.py
```

- [ ] **Step 5: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pipeline.py backend/main.py
git commit -m "perf: lazy-load bw_compress_pdf_blocking, remove unused subprocess import"
```

---

### Task 4: Cache SQLite DB connections in search_engine.py

**Files:**
- Modify: `D:\opencode\book-downloader\backend\search_engine.py:22,42-61`

**Impact:** HIGH — Eliminates multi-second DB copy on every search, caches connections.

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\search_engine.py`.

- [ ] **Step 2: Replace the _connect() method and add caching**

Find the `_connect()` method. Replace with a cached version:

```python
    def _connect(self, db_name: str) -> sqlite3.Connection:
        """Get or create a cached SQLite connection. Copies DB to temp if needed."""
        # Return cached connection if still valid
        if db_name in self._dbs:
            conn = self._dbs[db_name]
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.ProgrammingError:
                pass  # connection closed, re-open

        # Compute hash of source file to check if cache is stale
        source_path = os.path.join(self._db_dir, db_name)
        src_mtime = os.path.getmtime(source_path)

        # Use temp copy with mtime-based cache key
        cache_dir = os.path.join(tempfile.gettempdir(), "bdw_db_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cached = os.path.join(cache_dir, db_name)

        if not os.path.exists(cached) or os.path.getmtime(cached) < src_mtime:
            import shutil
            shutil.copy2(source_path, cached)

        conn = sqlite3.connect(cached, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA cache_size=-8000")  # 8MB cache
        self._dbs[db_name] = conn
        return conn
```

- [ ] **Step 3: Add cleanup on object destruction**

Add (or verify exists) a `close()` method:

```python
    def close(self):
        for conn in self._dbs.values():
            try:
                conn.close()
            except Exception:
                pass
        self._dbs.clear()
```

- [ ] **Step 4: Verify syntax**

```bash
python -m py_compile backend\search_engine.py
```

- [ ] **Step 5: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/search_engine.py
git commit -m "perf: cache SQLite connections with mtime-based invalidation, skip redundant copies"
```

---

### Self-Review

**1. Spec coverage:**
- Startup speed → Task 1 (eager imports) + Task 3 (lazy import)
- Dead code → Task 2 (duplicate endpoints)
- Search speed → Task 4 (cached connections)

**2. Placeholder scan:** No TBD/TODO. All code shown.

**3. Type consistency:**
- `self._dbs` type: `Dict[str, sqlite3.Connection]` — matches existing initializer
- `bw_compress_pdf_blocking` import moved from top-level to function-local — same signature
- Duplicate endpoints removed without changing active ones — no API change
