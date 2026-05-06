# Real-Time Progress Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time per-step progress, estimated time of arrival (ETA), and detail text for long-running pipeline steps (download, OCR) via WebSocket, and display them in the frontend.

**Architecture:** Extend the existing `step_progress` WebSocket event format (already used by OCR step) to include `detail` and `eta` fields. Add progress callbacks to synchronous download polling loops (stacks heartbeat, chunked HTTP streaming). Persist `step_detail` and `step_eta` in the task store so the REST polling fallback also sees them. Enhance `StepProgressBar` to show per-step progress bar with ETA text.

**Tech Stack:** Python 3.10+ (FastAPI, asyncio, threading.Lock for shared state) / TypeScript 5.x (React 18, Tailwind CSS)

---

## File Structure

| File | Change | Responsibility |
|------|--------|---------------|
| `backend/task_store.py` | Modify | Add `step_detail` and `step_eta` fields to task schema |
| `backend/engine/pipeline.py` | Modify | Add progress emission with detail/ETA to download steps (AA/stacks, direct, ZL, LibGen) |
| `frontend/src/types.ts` | Modify | Add `step_detail`, `step_eta` to `TaskItem`, `WSMessage` |
| `frontend/src/hooks/useTaskWebSocket.ts` | Modify | Pass `step_detail` and `step_eta` from `step_progress` messages |
| `frontend/src/components/StepProgressBar.tsx` | Modify | Show per-step percentage bar, detail text, ETA |
| `frontend/src/pages/TaskDetailPage.tsx` | Modify | Wire `step_detail`/`step_eta` into display |
| `frontend/src/pages/TaskListPage.tsx` | Modify | Show ETA for running tasks in list |

---

### Task 1: Backend — Add progress fields to task store schema

**Files:**
- Modify: `backend/task_store.py:56-80`

- [ ] **Step 1: Add `step_detail` and `step_eta` to TaskStore.create()**

```python
# In task_store.py TaskStore.create(), add two new fields after "progress": 0,
"step_detail": "",
"step_eta": "",
```

Edit at line ~70-71 of `task_store.py`:

```python
            "status": STATUS_PENDING,
            "current_step": "",
            "progress": 0,
            "step_detail": "",   # <-- new
            "step_eta": "",      # <-- new
            "logs": [],
```

- [ ] **Step 2: Add a helper method to update progress fields with WebSocket emit in one call**

Add to `TaskStore` class:

```python
    def update_progress(self, task_id: str, step: str, progress: int, detail: str = "", eta: str = "") -> Optional[Dict[str, Any]]:
        """Update progress fields and persist. Returns updated task or None."""
        return self.update(task_id, {
            "current_step": step,
            "progress": progress,
            "step_detail": detail,
            "step_eta": eta,
        })
```

- [ ] **Step 3: Commit**

```bash
git add backend/task_store.py
git commit -m "feat(task_store): add step_detail and step_eta fields for real-time progress"
```

---

### Task 2: Backend — Enhance `_emit` helper and add utility for progress with ETA

**Files:**
- Modify: `backend/engine/pipeline.py:35-40`

- [ ] **Step 1: Upgrade `_emit` to accept a unified progress payload**

Replace the existing `_emit` function (lines 35-40):

```python
async def _emit(task_id: str, event_type: str, data: Dict[str, Any]):
    """Broadcast a typed event to WebSocket subscribers for a task."""
    await ws_manager.broadcast_task(task_id, {
        "type": event_type,
        "task_id": task_id,
        **data,
    })
```

This already works; no changes needed. The existing callers already pass `detail` and `eta` in the `data` dict, and they are forwarded verbatim through `**data`.

- [ ] **Step 2: Add a progress emission helper with ETA computation**

Add after the `_emit` function (after line 40):

```python
async def _emit_progress(task_id: str, step: str, progress: int, detail: str = "", eta: str = ""):
    """Emit step_progress and persist to task_store atomically."""
    await _emit(task_id, "step_progress", {
        "step": step,
        "progress": progress,
        "detail": detail,
        "eta": eta,
    })
    task_store.update(task_id, {
        "step_detail": detail,
        "step_eta": eta,
    })
```

- [ ] **Step 3: Add ETA formatting utility**

Add a helper function:

```python
def _format_eta(remaining_seconds: float) -> str:
    """Format remaining seconds into a human-readable ETA string."""
    if remaining_seconds <= 0:
        return ""
    if remaining_seconds < 60:
        return f"约{int(remaining_seconds)}秒"
    minutes = int(remaining_seconds // 60)
    seconds = int(remaining_seconds % 60)
    if minutes < 60:
        return f"约{minutes}分{seconds}秒"
    hours = minutes // 60
    minutes = minutes % 60
    return f"约{hours}时{minutes}分"
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat(pipeline): add _emit_progress helper and ETA formatter"
```

---

### Task 3: Backend — Real-time progress for AA/Stacks download polling

**Files:**
- Modify: `backend/engine/pipeline.py:527-719` (`_stacks_sync_download`)

- [ ] **Step 1: Add progress_callback parameter to `_stacks_sync_download`**

The function is synchronous and runs via `run_in_executor`. We need to pass a mutable progress container. Add a parameter and emit inside the polling loop.

```python
def _stacks_sync_download(md5: str, dl_dir: str, ss_code: str = "",
                           progress_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
```

At the top, add:

```python
    if progress_data is None:
        progress_data = {}
```

In the heartbeat polling loop (line ~652-718), after each sleep add:

```python
                        # Emit progress via shared mutable dict
                        if progress_data is not None:
                            elapsed = time.time() - deadline + stacks_timeout
                            elapsed = max(elapsed, 1)
                            pct = min(int(elapsed / stacks_timeout * 100), 99)
                            remaining = int(deadline - time.time())
                            eta_str = _format_eta(max(remaining, 0))
                            progress_data["progress"] = pct
                            progress_data["detail"] = f"AA stacks 下载中... ({remaining}s 剩余)"
                            progress_data["eta"] = eta_str
```

- [ ] **Step 2: Update caller to read progress and emit via WebSocket**

In `_download_via_aa_and_stacks`, after line 723 where `_stacks_sync_download` is called via `run_in_executor`:

```python
                    # Set up shared progress container
                    _progress: Dict[str, Any] = {}
                    download_dir = config.get("download_dir", "")
                    ss_code_local = report.get("ss_code", "")
                    
                    # Start stacks download in executor
                    _future = asyncio.get_event_loop().run_in_executor(
                        None, _stacks_sync_download, md5, download_dir, ss_code_local, _progress)
                    
                    # Poll progress every 3 seconds while waiting
                    while not _future.done():
                        await asyncio.sleep(3)
                        if _progress:
                            await _emit_progress(
                                task_id, "download_pages",
                                _progress.get("progress", 50),
                                _progress.get("detail", ""),
                                _progress.get("eta", ""),
                            )
                    
                    stack_result = await _future
```

The original code at line 723-725:

```python
                    stack_result = await asyncio.get_event_loop().run_in_executor(
                        None, _stacks_sync_download, md5, download_dir, ss_code_local)
```

Replace with the polling pattern shown above.

- [ ] **Step 3: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat(pipeline): real-time progress for AA/stacks download polling"
```

---

### Task 4: Backend — Real-time progress for direct download (FlareSolverr CDN + ZL + LibGen)

**Files:**
- Modify: `backend/engine/pipeline.py:756-790` (AA FlareSolverr direct download section)
- Modify: `backend/engine/pipeline.py:989-1054` (ZL download section)
- Modify: `backend/engine/pipeline.py:793-866` (LibGen download section)

- [ ] **Step 1: Add chunk-streaming progress to AA FlareSolverr direct download**

Find the section in `_download_via_aa_and_stacks` (around line 756-790) where direct CDN download chunks are written. After the `fs_resp = _req.get(fs_url, ... stream=True)` and before the chunk loop, add:

```python
                        _total_size = int(fs_resp.headers.get("Content-Length", 0))
                        _downloaded = 0
                        _dl_start = time.time()
```

Inside the chunk loop (`for chunk in fs_resp.iter_content(65536):`), add:

```python
                            if chunk:
                                _downloaded += len(chunk)
                                if _total_size > 0 and _downloaded % (65536 * 100) == 0:  # every ~6.5MB
                                    _pct = int(_downloaded / _total_size * 100)
                                    _elapsed = time.time() - _dl_start
                                    _speed = _downloaded / _elapsed / 1024 / 1024 if _elapsed > 0 else 0
                                    _remaining = (_total_size - _downloaded) / (_downloaded / _elapsed) if _downloaded > 0 else 0
                                    await _emit_progress(
                                        task_id, "download_pages",
                                        _pct,
                                        f"下载中... {_downloaded//1024//1024}MB/{_total_size//1024//1024}MB ({_speed:.1f} MB/s)",
                                        _format_eta(_remaining),
                                    )
```

- [ ] **Step 2: Add stage progress to Z-Library download**

In `_step_download_pages`, in the ZL section (around line 989-1054), add progress emits before and after each stage:

Before the login call (around line 1002):
```python
        await _emit_progress(task_id, "download_pages", 55, "ZL 登录中...", "")
```

After login success (around line 1004):
```python
        await _emit_progress(task_id, "download_pages", 60, f"ZL {balance}", "")
```

After search (around line 1013):
```python
        await _emit_progress(task_id, "download_pages", 70, f"ZL 搜索到 {len(candidates)} 个候选", "")
```

While waiting for user confirmation (in `_wait_for_user_confirmation`, around line 899):
```python
        await _emit_progress(task_id, "download_pages", 75, "等待用户选择...", "")
```

After ZL download complete (around line 1036):
```python
        await _emit_progress(task_id, "download_pages", 90, "ZL 下载完成，验证中...", "")
```

- [ ] **Step 3: Add stage progress to LibGen download**

In `_download_via_libgen`, at the start:
```python
    await _emit_progress(task_id, "download_pages", 80, f"LibGen: 搜索中...", "")
```

Before downloading results (after search):
```python
    await _emit_progress(task_id, "download_pages", 85, f"LibGen: 找到 {len(results)} 个结果，下载中...", "")
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat(pipeline): real-time progress for direct, ZL, and LibGen downloads"
```

---

### Task 5: Backend — Ensure OCR progress detail persists across page refreshes

**Files:**
- Modify: `backend/engine/pipeline.py:1456`

- [ ] **Step 1: Replace raw `_emit` with `_emit_progress` in OCR step**

In `_step_ocr`, find the progress emit inside the stderr reader (line ~1455). Currently it reads:

```python
                            await _emit(task_id, "step_progress", {
                                "step": "ocr", "progress": _pct,
                                "detail": f"{_page_cur}/{_page_tot} 页",
                                "eta": _eta_str,
                            })
                            task_store.update(task_id, {
                                "ocr_progress": _pct,
                                "ocr_detail": f"{_page_cur}/{_page_tot} 页",
                            })
```

Replace with:

```python
                            await _emit_progress(
                                task_id, "ocr", _pct,
                                f"{_page_cur}/{_page_tot} 页",
                                _eta_str,
                            )
```

This consolidates emit + persist into one call, and ensures `step_detail`/`step_eta` are always in sync.

- [ ] **Step 2: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat(pipeline): use _emit_progress in OCR step for persistence"
```

---

### Task 6: Frontend — Add progress fields to types

**Files:**
- Modify: `frontend/src/types.ts:34-52`

- [ ] **Step 1: Add `step_detail` and `step_eta` to `TaskItem`**

In `frontend/src/types.ts`, add to the `TaskItem` interface:

```typescript
export interface TaskItem {
  task_id: string
  book_id: string
  title: string
  isbn: string
  ss_code: string
  source: string
  bookmark?: string | null
  authors: string[]
  publisher: string
  status: TaskStatus
  current_step: string
  progress: number
  step_detail?: string   // <-- new
  step_eta?: string      // <-- new
  logs: string[]
  error: string
  report: TaskReport
  created_at: number
  updated_at: number
}
```

- [ ] **Step 2: Add `detail` and `eta` to `WSMessage` if not already there**

`WSMessage` already uses `[key: string]: unknown`, so it will accept the new fields. No change needed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types.ts
git commit -m "feat(types): add step_detail and step_eta to TaskItem"
```

---

### Task 7: Frontend — Update WebSocket hook to pass through detail and eta

**Files:**
- Modify: `frontend/src/hooks/useTaskWebSocket.ts:49-57`

- [ ] **Step 1: Pass `detail` and `eta` from `step_progress` message**

In the `step_progress` handler (lines 49-57):

```typescript
          if (msg.type === 'step_progress' && msg.task_id === taskId) {
            if (onUpdate) {
              const pendingTask: Partial<TaskItem> = {
                task_id: taskId,
                current_step: msg.step || '',
                progress: msg.progress || 0,
                step_detail: msg.detail as string | undefined,
                step_eta: msg.eta as string | undefined,
              } as TaskItem
              onUpdate(pendingTask as TaskItem)
            }
          }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/hooks/useTaskWebSocket.ts
git commit -m "feat(hooks): forward step_detail and step_eta from WS messages"
```

---

### Task 8: Frontend — Rewrite StepProgressBar with per-step progress and ETA

**Files:**
- Modify: `frontend/src/components/StepProgressBar.tsx` (complete rewrite)

- [ ] **Step 1: Write the new component**

Replace the entire file:

```tsx
import { PIPELINE_STEPS } from '../constants'
import type { TaskItem } from '../types'

interface StepProgressBarProps {
  task: TaskItem
}

export default function StepProgressBar({ task }: StepProgressBarProps) {
  const currentStepIdx = PIPELINE_STEPS.findIndex((s) => s.key === task.current_step)

  // Resolve per-step progress: for the active step, use task.progress as percentage within that step
  // For completed steps, treat as 100%. For pending steps, 0%.
  const stepProgress = (idx: number): number => {
    if (idx < currentStepIdx) return 100
    if (idx > currentStepIdx) return 0
    if (task.status === 'completed') return 100
    return task.progress ?? 0
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold text-gray-600">处理步骤</h4>
        {task.step_detail && (
          <span className="text-xs text-gray-500 truncate max-w-[200px]">
            {task.step_detail}
          </span>
        )}
      </div>

      {/* Step circles with progress bars */}
      <div className="flex items-center gap-0">
        {PIPELINE_STEPS.map((step, idx) => {
          const isDone = idx < currentStepIdx || (idx === currentStepIdx && task.status === 'completed')
          const isActive = idx === currentStepIdx && task.status === 'running'
          const isPending = idx > currentStepIdx || (task.status === 'pending' && idx > 0)
          const isFailed = idx === currentStepIdx && task.status === 'failed'
          const pct = stepProgress(idx)

          return (
            <div key={step.key} className="flex-1 flex flex-col items-center relative">
              {/* Connector line */}
              {idx > 0 && (
                <div
                  className="absolute"
                  style={{ left: '-50%', right: '50%', top: 12, height: 2, zIndex: 0 }}
                >
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: isDone ? '100%' : isActive ? `${pct}%` : '0%',
                      backgroundColor: isDone ? '#10b981' : '#60a5fa',
                    }}
                  />
                  <div
                    className="h-full bg-gray-200"
                    style={{
                      width: isDone ? '0%' : isActive ? `${100 - pct}%` : '100%',
                    }}
                  />
                </div>
              )}

              {/* Circle */}
              <div className="relative z-10 flex flex-col items-center">
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                    isFailed
                      ? 'bg-red-500 text-white'
                      : isDone
                      ? 'bg-green-500 text-white'
                      : isActive
                      ? 'bg-blue-500 text-white ring-2 ring-blue-200'
                      : 'bg-gray-200 text-gray-400'
                  }`}
                >
                  {isDone ? '✓' : idx + 1}
                </div>
                <span
                  className={`mt-1 text-[10px] text-center max-w-[72px] leading-tight ${
                    isActive ? 'text-blue-600 font-medium' : 'text-gray-400'
                  }`}
                >
                  {step.label}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Per-step progress bar (only visible when running) */}
      {task.status === 'running' && currentStepIdx >= 0 && (
        <div className="mt-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] text-gray-500">
              {PIPELINE_STEPS[currentStepIdx]?.label} 进度
            </span>
            <span className="text-[11px] text-gray-400">{stepProgress(currentStepIdx)}%</span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${stepProgress(currentStepIdx)}%` }}
            />
          </div>

          {/* ETA display */}
          {task.step_eta && (
            <div className="flex items-center gap-1 mt-1">
              <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-[11px] text-gray-400">预计剩余 {task.step_eta}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/StepProgressBar.tsx
git commit -m "feat(StepProgressBar): per-step progress bar with ETA display"
```

---

### Task 9: Frontend — Wire progress into TaskDetailPage

**Files:**
- Modify: `frontend/src/pages/TaskDetailPage.tsx`

- [ ] **Step 1: Ensure `step_progress` handler forwards new fields**

The existing handler in `TaskDetailPage.tsx:43-49` already catches `step_progress` and updates `current_step` and `progress`. The WebSocket hook now also passes `step_detail` and `step_eta`, and the `handleWSMessage` function merges `msg.task` via the `task_update` handler (line 40-42). However, the `step_progress` handler on lines 43-49 only sets `current_step` and `progress`. We need to add `step_detail` and `step_eta`:

```typescript
    if (msg.type === 'step_progress') {
      setTask((prev) =>
        prev
          ? {
              ...prev,
              current_step: msg.step || prev.current_step,
              progress: msg.progress || prev.progress,
              step_detail: (msg.detail as string) || prev.step_detail,
              step_eta: (msg.eta as string) || prev.step_eta,
            }
          : prev
      )
    }
```

- [ ] **Step 2: Add an ETA badge near the task header**

Add after the status badge (after line 136, inside the header flex):

```tsx
              {task.status === 'running' && task.step_eta && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-600 border border-blue-200">
                  <svg className="w-3 h-3 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  剩余 {task.step_eta}
                </span>
              )}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/TaskDetailPage.tsx
git commit -m "feat(TaskDetailPage): show ETA badge from step_eta field"
```

---

### Task 10: Frontend — Show ETA in task list for running tasks

**Files:**
- Modify: `frontend/src/pages/TaskListPage.tsx:104-160` (the task row rendering)

- [ ] **Step 1: Add ETA column in progress cell**

In the task row's progress cell (around line 116-125), replace:

```tsx
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500 rounded-full transition-all"
                          style={{ width: `${task.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-400">{task.progress}%</span>
                    </div>
                  </td>
```

With:

```tsx
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500 rounded-full transition-all"
                          style={{ width: `${task.progress}%` }}
                        />
                      </div>
                      <div className="flex flex-col">
                        <span className="text-xs text-gray-400">{task.progress}%</span>
                        {task.status === 'running' && task.step_eta && (
                          <span className="text-[10px] text-gray-400 whitespace-nowrap">
                            {task.step_eta}
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/TaskListPage.tsx
git commit -m "feat(TaskListPage): show ETA for running tasks in list view"
```

---

### Task 11: Verification — Smoke test

- [ ] **Step 1: Run the smoke test to verify no regressions**

Run: `python test_smoke.py`
Expected: All tests pass (22/22 or similar).

- [ ] **Step 2: Check frontend TypeScript compilation**

Run: `cd frontend && npx tsc --noEmit` (or `npm run build` to check full build)
Expected: No TypeScript errors.

- [ ] **Step 3: Commit any necessary fixes**

```bash
git add -A
git commit -m "chore: fix type/compilation issues from progress feedback implementation"
```

---

## Self-Review

### 1. Spec coverage
- Real-time progress for long-running tasks (>3 min): Task 3 (AA/stacks polling), Task 4 (direct/ZL/LibGen download), Task 5 (OCR)
- ETA display: Task 8 (StepProgressBar), Task 9 (TaskDetailPage badge), Task 10 (TaskListPage)
- Per-step progress bar: Task 8 (StepProgressBar rewrite)
- Detail text: Task 8 (header in StepProgressBar shows step_detail)
- Persistence across page refreshes: Task 1 (task_store fields), Task 2 (_emit_progress persists), Task 5 (OCR uses _emit_progress)

### 2. Placeholder scan
No placeholders (TBD, TODO, "fill in details", "similar to"). Every code block is complete.

### 3. Type consistency
- `step_detail`: string, used in TaskItem, WSMessage, task_store, _emit_progress — consistent
- `step_eta`: string, used in TaskItem, WSMessage, task_store, _emit_progress, _format_eta — consistent
- `_emit_progress(task_id, step, progress, detail, eta)` matches all callers
- `_format_eta(remaining_seconds: float) -> str` matches usage in Task 3 and Task 4

All good.
