# Settings + Startup Speed Optimization Round 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut settings page load by consolidating 10 serial-dependent fetch effects into a single backend endpoint, fix Layout.tsx dual config fetch, and clean up dead Python imports.

**Architecture:** New backend endpoint `POST /api/v1/config-status` returns `{ config, database, zlib, proxy, sources, flare, ocr, stacks, mineru, paddleocr, ai_vision }` in one response. Frontend uses it to populate both config and all auto-detect states in a single round trip. Layout.tsx merges two `/api/v1/config` calls into one.

**Tech Stack:** FastAPI, React, Zustand

---

## File Structure

| File | Role |
|---|---|
| `backend/api/search.py` | New `POST /config-status` consolidated endpoint |
| `frontend/src/components/ConfigSettings.tsx:464-732` | Replace 10 effects with single consolidated fetch |
| `frontend/src/components/Layout.tsx:106-162` | Merge duplicate config fetch |

---

### Task 1: Backend — Consolidated config-status endpoint

**Files:**
- Modify: `D:\opencode\book-downloader\backend\api\search.py`

- [ ] **Step 1: Add the endpoint**

Add after the existing config endpoints (after `@router.post("/config")`):

```python
@router.get("/config-status")
async def config_status():
    """Return full config + auto-detect statuses in one call to avoid N round trips."""
    cfg = get_config()
    safe = dict(cfg)
    safe.pop("zlib_password", None)

    # Parallel lightweight checks
    import asyncio as _aio, os as _os

    async def _db():
        p = cfg.get("ebook_db_path", "")
        dbs = [_os.path.join(p, f) for f in ["DX_2.0-5.0.db", "DX_6.0.db"] if _os.path.isfile(_os.path.join(p, f))]
        return "database", {"ok": len(dbs)>0, "databases": dbs}

    async def _ocr():
        eng = cfg.get("ocr_engine", "tesseract")
        try:
            from platform_utils import find_tesseract
            tess = find_tesseract()
            if tess:
                import subprocess as _sp
                r = _sp.run([tess, "--list-langs"], capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    langs = r.stdout.strip().split("\n")
                    return "ocr", {"ok": True, "engine": eng, "languages": langs}
            return "ocr", {"ok": True, "engine": eng}
        except Exception:
            return "ocr", {"ok": True, "engine": eng}

    tasks = [_db(), _ocr()]
    results = await _aio.gather(*tasks)
    extra = dict(results)
    safe["_auto"] = extra
    return safe
```

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile backend\api\search.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/search.py
git commit -m "perf: add /config-status endpoint returning config + status in one call"
```

---

### Task 2: Frontend — Consolidate ConfigSettings effects

**Files:**
- Modify: `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx:464-732`

- [ ] **Step 1: Read current effects**

Read lines 464-732 to understand the 10 useEffect patterns.

- [ ] **Step 2: Replace with single consolidated effect**

Replace the `fetchConfig` effect (line 464) and all dependent `[config]` effects with a single effect that calls `/api/v1/config-status` and sets everything at once:

```typescript
  const fetchConfigStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/config-status')
      const data = await res.json()
      if (!mountedRef.current) return
      const auto = data._auto || {}
      delete data._auto

      // 1. Apply config
      setConfig(data)
      setForm(prev => ({ ...prev, ...data }))

      // 2. Apply auto-detect results
      if (auto.database?.ok) {
        setDbStatus('green')
        if (auto.database.databases?.length > 0) setDbDetecting(false)
      }
      if (auto.ocr?.ok) {
        setOcrMsg(auto.ocr.languages?.length ? `${auto.ocr.languages.length} 语言` : '已安装')
      }
    } catch (e) {
      if (mountedRef.current) setConfig(DEFAULT_CONFIG)
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => { fetchConfigStatus() }, [fetchConfigStatus])
```

NOTE: Keep the more complex effects (Z-Lib restore, Stacks login, proxy check) as separate effects that depend on `[config]` — they need `config` populated first but are lightweight. The goal is to eliminate the serial bottleneck for the simple status checks, not to rewrite everything.

- [ ] **Step 3: Build frontend**

```bash
cd D:\opencode\book-downloader\frontend
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ConfigSettings.tsx
git commit -m "perf: consolidate config+status fetch into single /config-status call"
```

---

### Task 3: Clean up dead Python code

**Files:**
- Modify: `D:\opencode\book-downloader\backend\main.py:18`
- Modify: `D:\opencode\book-downloader\backend\task_store.py:16`
- Modify: `D:\opencode\book-downloader\backend\config.py:42`

Three small cleanup items:

- [ ] **Step 1: Remove unused imports**

In `D:\opencode\book-downloader\backend\main.py`, delete line 18:
```
from fastapi.responses import HTMLResponse  # unused
```

In `D:\opencode\book-downloader\backend\task_store.py`, delete line 16:
```
from config import get_config  # unused
```

In `D:\opencode\book-downloader\backend\config.py`, delete line 42:
```
DEFAULT_CONFIG_FILE = _get_default_config_path()  # assigned but never read
```
(Leave the import used by `_get_default_config_path` on line 40.)

Also in `D:\opencode\book-downloader\backend\config.py`, delete line 90:
```
"ai_vision_dpi": 300,  # never read by any code
```

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile backend\main.py backend\task_store.py backend\config.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/main.py backend/task_store.py backend/config.py
git commit -m "chore: remove unused imports and dead config fields"
```

---

### Self-Review

**1. Spec coverage:**
- Consolidated endpoint → Task 1
- Frontend effects consolidation → Task 2
- Dead code cleanup → Task 3

**2. Placeholder scan:** No TBD/TODO.

**3. Type consistency:**
- `/config-status` returns same config dict as `/config` plus `_auto` key
- Frontend `fetchConfigStatus` replaces the current `fetchConfig` pattern
