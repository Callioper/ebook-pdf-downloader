# Stacks Download Failure Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect AA download failures in stacks via the `/api/status` endpoint and immediately report the failure reason in the task log, instead of silently waiting for the 600s heartbeat timeout.

**Architecture:** Extract a pure `_detect_stacks_failure(status_data, md5) -> Optional[str]` helper from the `_stacks_sync_download` heartbeat loop. The helper inspects `queue[]`, `current`, and `recent_history` fields in the `/api/status` JSON response for `failed_at` / `status=="failed"` / `error` fields. When a failure is detected, the heartbeat loop additionally fetches `/api/logs` for the last 20 lines of stacks-internal error detail (403, mirror fail, etc.), logs everything via `task_store.add_log`, and returns `None` immediately.

**Tech Stack:** Python 3.10+, `requests`, `pytest`, `unittest.mock.patch`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/engine/aa_downloader.py` | **Modify** | Add `_detect_stacks_failure()` helper function |
| `backend/engine/pipeline.py` | **Modify** | Integrate failure detection into `_stacks_sync_download` heartbeat loop (line ~1322) |
| `tests/test_stacks_failure_detect.py` | **Create** | Unit tests for `_detect_stacks_failure()` |

---

### Task 1: Write the failure-detection helper and its tests

**Files:**
- Create: `tests/test_stacks_failure_detect.py`
- Modify: `backend/engine/aa_downloader.py` (append function)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stacks_failure_detect.py
import pytest
from engine.aa_downloader import _detect_stacks_failure

MD5 = "b199088731ad6191afcde1e6d21b7254"


def test_detect_failure_current_item():
    """Failure on the `current` item with failed_at + error."""
    data = {
        "current": {
            "md5": MD5,
            "failed_at": "2026-05-16T20:49:39",
            "error": "Mirror annas-archive.pk failed",
            "status": "failed",
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "annas-archive.pk" in msg


def test_detect_failure_queue_item():
    """Failure on a queue item."""
    data = {
        "current": None,
        "queue": [
            {
                "md5": MD5,
                "failed_at": "2026-05-16T20:49:39",
                "error_message": "Got 403 but no FlareSolverr configured",
                "status": "failed",
            }
        ],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "403" in msg


def test_detect_failure_history_item():
    """Failure in recent_history."""
    data = {
        "current": None,
        "queue": [],
        "recent_history": [
            {
                "md5": MD5,
                "failed_at": "2026-05-16T20:49:39",
                "error": "Download timeout",
                "status": "failed",
            }
        ],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "timeout" in msg


def test_no_failure_no_matching_md5():
    """Item exists but is not failed — no match returned."""
    data = {
        "current": {
            "md5": MD5,
            "progress": {"percent": 45, "speed": 102400, "downloaded": 1000000, "total_size": 2000000},
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_different_md5():
    """A different MD5 failed — our MD5 should not match."""
    data = {
        "current": {
            "md5": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "failed_at": "2026-05-16T20:49:39",
            "error": "some other failure",
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_status_not_failed():
    """Item has no failed_at and status is not 'failed'."""
    data = {
        "current": {
            "md5": MD5,
            "status": "downloading",
            "progress": {"percent": 70},
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_empty_status():
    data = {"current": None, "queue": [], "recent_history": []}
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_missing_keys():
    data = {}
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_detect_failure_fallback_to_status_message():
    """When `error` is absent but `status_message` says 'failed'."""
    data = {
        "current": {
            "md5": MD5,
            "failed_at": "2026-05-16T20:49:39",
            "status_message": "Mirror download failed",
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "Mirror download failed" in msg
```

- [ ] **Step 2: Run tests to verify they all fail**

Run: `cd D:\opencode\book-downloader\backend && python -m pytest ..\tests\test_stacks_failure_detect.py -v`
Expected: All 9 tests FAIL with `ModuleNotFoundError: No module named 'engine.aa_downloader'` or `ImportError: cannot import name '_detect_stacks_failure'`

- [ ] **Step 3: Implement the minimal `_detect_stacks_failure` function**

Append to `backend/engine/aa_downloader.py`:

```python
def _detect_stacks_failure(status_data: dict, md5: str) -> Optional[str]:
    """
    Inspect a GET /api/status response for a failed queue item matching md5.
    Returns the error message if found, or None if the item is not in a failed state.
    Checks `current`, `queue[]`, and `recent_history[]` in that order.
    """
    if not isinstance(status_data, dict):
        return None

    # Candidate containers to inspect
    current = status_data.get("current")
    queue_items = status_data.get("queue", []) or []
    history_items = status_data.get("recent_history", []) or []

    # Normalise `current` into a list for uniform iteration
    candidates = []
    if isinstance(current, dict) and current.get("md5") == md5:
        candidates.append(current)
    for item in queue_items:
        if isinstance(item, dict) and item.get("md5") == md5:
            candidates.append(item)
    for item in history_items:
        if isinstance(item, dict) and item.get("md5") == md5:
            candidates.append(item)

    for item in candidates:
        # Check explicit failure indicators
        is_failed = (
            item.get("failed_at")
            or item.get("status") == "failed"
        )
        if not is_failed:
            continue
        # Extract the most descriptive error field
        msg = (
            item.get("error")
            or item.get("error_message")
            or item.get("status_message")
            or item.get("message")
            or "unknown error"
        )
        return str(msg)

    return None
```

- [ ] **Step 4: Run tests to verify they all pass**

Run: `cd D:\opencode\book-downloader\backend && python -m pytest ..\tests\test_stacks_failure_detect.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\opencode\book-downloader
git add tests/test_stacks_failure_detect.py backend/engine/aa_downloader.py
git commit -m "feat: add _detect_stacks_failure helper for stacks /api/status failure detection"
```

---

### Task 2: Integrate failure detection into the heartbeat loop

**Files:**
- Modify: `backend/engine/pipeline.py:1317-1326` (inside `_stacks_sync_download`)

- [ ] **Step 1: Update the import in pipeline.py**

The `_detect_stacks_failure` helper lives in `aa_downloader.py`. Verify it is already imported at line 860:

```python
from engine.aa_downloader import search_aa, get_md5_details, batch_get_md5_details, get_stacks_api_key, _calc_title_relevance, verify_md5, resolve_download_url
```

Add `_detect_stacks_failure` to the existing import:

```python
from engine.aa_downloader import search_aa, get_md5_details, batch_get_md5_details, get_stacks_api_key, _calc_title_relevance, verify_md5, resolve_download_url, _detect_stacks_failure
```

- [ ] **Step 2: Add failure detection block after progress-tracking code**

In `backend/engine/pipeline.py`, find the block at lines 1317-1326 (the `cur` / `active_items` checking). Insert the failure detection block **immediately after** the progress tracking `if dl_info:` block ends (after line 1341):

Replace the following range of code:

```python
                if cur and isinstance(cur, dict) and cur.get("md5") == md5:
                    active_items = [cur]
                dl_info = None
                for item in active_items:
                    if isinstance(item, dict) and item.get("md5") == md5 and not item.get("completed_at"):
                        dl_info = item
                        break
                if dl_info:
                    progress = dl_info.get("progress", {})
                    if isinstance(progress, dict):
                        pct_val = progress.get("percent", 0)
                        speed_bps = progress.get("speed", 0)
                        downloaded = progress.get("downloaded", 0)
                        total_size = progress.get("total_size", 0)
                        speed_str = f"{speed_bps / 1024:.0f} KB/s" if speed_bps > 0 else ""
                        if progress_data is not None:
                            progress_data["progress"] = pct_val
                            progress_data["detail"] = f"stacks {pct_val:.0f}% {speed_str}"
                            if speed_bps > 0 and total_size > downloaded:
                                eta_s = (total_size - downloaded) / speed_bps
                                progress_data["eta"] = _format_eta(int(eta_s))
                    remaining = int(time.time() - start_time)
                    if remaining % 6 == 0:
                        elapsed_s = int(time.time() - start_time)
                        status_msg = dl_info.get("status_message", "downloading")
                        task_store.add_log(task_id, f"AA: stacks {status_msg} ({pct_val:.0f}%, {speed_str}) ({elapsed_s}s)")
                else:
                    remaining = int(time.time() - start_time)
                    if remaining % 15 == 0:
                        elapsed_s = int(time.time() - start_time)
                        task_store.add_log(task_id, f"AA: stacks heartbeat ({elapsed_s}s)...")
```

with:

```python
                if cur and isinstance(cur, dict) and cur.get("md5") == md5:
                    active_items = [cur]
                dl_info = None
                for item in active_items:
                    if isinstance(item, dict) and item.get("md5") == md5 and not item.get("completed_at"):
                        dl_info = item
                        break

                # 3d. Failure detection — check /api/status for a failed item
                failed_msg = _detect_stacks_failure(sd, md5)
                if failed_msg:
                    # Try to extract detail from stacks' own logs
                    log_detail_lines = []
                    try:
                        lr = _req.get(f"{url}/api/logs", headers=_bearer(), timeout=5)
                        if lr.status_code == 200:
                            for line in lr.text.splitlines()[-20:]:
                                lowered = line.lower()
                                if md5[:8] in lowered or any(
                                    kw in lowered for kw in ("failed", "403", "error", "mirror", "refused")
                                ):
                                    log_detail_lines.append(line.strip()[:200])
                    except Exception:
                        pass

                    task_store.add_log(task_id, f"AA: stacks download FAILED: {failed_msg}")
                    if log_detail_lines:
                        for ln in log_detail_lines:
                            task_store.add_log(task_id, f"AA: stacks log | {ln}")

                    if progress_data is not None:
                        progress_data["progress"] = 0
                        progress_data["detail"] = f"stacks failed: {failed_msg[:80]}"
                        progress_data["eta"] = ""

                    return None  # bail immediately — no point waiting for timeout

                if dl_info:
                    progress = dl_info.get("progress", {})
                    if isinstance(progress, dict):
                        pct_val = progress.get("percent", 0)
                        speed_bps = progress.get("speed", 0)
                        downloaded = progress.get("downloaded", 0)
                        total_size = progress.get("total_size", 0)
                        speed_str = f"{speed_bps / 1024:.0f} KB/s" if speed_bps > 0 else ""
                        if progress_data is not None:
                            progress_data["progress"] = pct_val
                            progress_data["detail"] = f"stacks {pct_val:.0f}% {speed_str}"
                            if speed_bps > 0 and total_size > downloaded:
                                eta_s = (total_size - downloaded) / speed_bps
                                progress_data["eta"] = _format_eta(int(eta_s))
                    remaining = int(time.time() - start_time)
                    if remaining % 6 == 0:
                        elapsed_s = int(time.time() - start_time)
                        status_msg = dl_info.get("status_message", "downloading")
                        task_store.add_log(task_id, f"AA: stacks {status_msg} ({pct_val:.0f}%, {speed_str}) ({elapsed_s}s)")
                else:
                    remaining = int(time.time() - start_time)
                    if remaining % 15 == 0:
                        elapsed_s = int(time.time() - start_time)
                        task_store.add_log(task_id, f"AA: stacks heartbeat ({elapsed_s}s)...")
```

- [ ] **Step 3: Run the full test suite to verify no regressions**

Run: `cd D:\opencode\book-downloader\backend && python -m pytest ..\tests\ -v`
Expected: All existing tests pass + 9 new tests pass

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pipeline.py
git commit -m "feat: detect stacks download failure via /api/status and report reason in task log"
```

---

### Task 3: Add `/api/logs`-based failure enrichment for empty error messages

**Files:**
- Modify: `backend/engine/pipeline.py` (the failure-detection block added in Task 2)
- Modify: `tests/test_stacks_failure_detect.py`

If `_detect_stacks_failure` returns only `"unknown error"` (no descriptive field found), the `/api/logs` fetch becomes the primary source of failure detail. Verify this path works.

- [ ] **Step 1: Write test for the "unknown error" → log-enrichment path**

Append to `tests/test_stacks_failure_detect.py`:

```python
def test_detect_failure_no_error_field_returns_unknown():
    """Item is failed but has no error/error_message/status_message fields."""
    data = {
        "current": {
            "md5": MD5,
            "failed_at": "2026-05-16T20:49:39",
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg == "unknown error"
```

- [ ] **Step 2: Run to verify the test passes**

Run: `cd D:\opencode\book-downloader\backend && python -m pytest ..\tests\test_stacks_failure_detect.py::test_detect_failure_no_error_field_returns_unknown -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add tests/test_stacks_failure_detect.py
git commit -m "test: verify unknown error fallback in stacks failure detection"
```

---

## Self-Review

### 1. Spec coverage

| Requirement | Task | Status |
|---|---|---|
| Monitor AA download progress | Task 2 (existing progress tracking unchanged) | N/A (already works) |
| Detect download failure via stacks API | Task 1 (`_detect_stacks_failure` helper) + Task 2 (integration) | Covered |
| Report failure reason in task log | Task 2 (`task_store.add_log` with failed_msg + log_detail_lines) | Covered |
| Use stacks API per the reference docs | Uses `GET /api/status` (documented) and `GET /api/logs` (documented, admin key) | Covered |

### 2. Placeholder scan
- No "TBD", "TODO", or "implement later" markers found — every step has concrete code.
- No "add appropriate error handling" without code — error handling is shown in full.
- No "write tests for the above" without test code — all test functions are complete.

### 3. Type consistency
- `_detect_stacks_failure(status_data: dict, md5: str) -> Optional[str]` defined in Task 1, called in Task 2 with `sd` (the parsed JSON dict from `/api/status`) and `md5` (the target MD5 string). Types match.
- `_detect_stacks_failure` is imported in `pipeline.py` line 860 alongside the other `aa_downloader` symbols. Name is consistent.
