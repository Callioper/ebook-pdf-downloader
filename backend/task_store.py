# -*- coding: utf-8 -*-
# 职责：任务存储管理，内存字典 + JSON 文件持久化
# 入口函数：TaskStore.create(), get(), list_all(), update(), delete(), cancel()
# 依赖：config
# 注意：线程安全，使用 Lock 保护并发访问

import json
import os
import sys as _sys
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from config import get_config
from config import APP_DATA_DIR as _app_data

def _get_tasks_path() -> Path:
    if getattr(_sys, 'frozen', False):
        _app_data.mkdir(parents=True, exist_ok=True)
        return _app_data / "tasks.json"
    return Path(__file__).resolve().parent.parent / "tasks.json"

TASKS_FILE = _get_tasks_path()

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

PIPELINE_STEPS = [
    "fetch_metadata",
    "fetch_isbn",
    "download_pages",
    "convert_pdf",
    "ocr",
    "bookmark",
    "finalize",
]


class TaskStore:
    def __init__(self):
        self._lock = Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        self._stopping = False
        self._update_counter: Dict[str, int] = {}
        self._log_counter: Dict[str, int] = {}
        self._load()
        self._start_save_worker()
        self._start_purge_worker()

    def _load(self):
        if TASKS_FILE.exists():
            try:
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    self._tasks = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._tasks = {}
        # Reset stale running tasks on startup (>1h since last update)
        _now = time.time()
        _stale_count = 0
        for tid, t in self._tasks.items():
            if t.get("status") == STATUS_RUNNING:
                _age = _now - t.get("updated_at", t.get("created_at", 0))
                if _age > 3600:
                    t["status"] = STATUS_FAILED
                    t["error"] = "Task stalled (app restarted)"
                    t["logs"] = (t.get("logs") or []) + [f"[{time.strftime('%H:%M:%S')}] Auto-failed: task was running for >1h before app restart"]
                    _stale_count += 1
        if _stale_count:
            self._mark_dirty()

    def _mark_dirty(self):
        """Called under self._lock - signals background thread to flush to disk."""
        self._dirty = True

    def _start_save_worker(self):
        """Background thread: writes dirty state to disk every 0.5s, outside lock."""
        import threading as _th

        def _worker():
            while not self._stopping:
                _th.Event().wait(0.5)
                with self._lock:
                    if not self._dirty:
                        continue
                    try:
                        data = json.dumps(
                            self._tasks, ensure_ascii=False, indent=2
                        )
                    except Exception:
                        continue
                    self._dirty = False
                # Write outside lock
                try:
                    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    tmp = str(TASKS_FILE) + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(data)
                    os.replace(tmp, str(TASKS_FILE))
                except (PermissionError, OSError):
                    pass

        t = _th.Thread(target=_worker, daemon=True, name="taskstore-saver")
        t.start()

    def _start_purge_worker(self):
        """Background thread: purges completed tasks from memory every 10 min."""
        import threading as _th

        def _worker():
            while not self._stopping:
                _th.Event().wait(600)
                self._purge_stale_completed()

        t = _th.Thread(target=_worker, daemon=True, name="taskstore-purger")
        t.start()

    def _purge_stale_completed(self):
        """Remove completed/failed/cancelled tasks >1h old from memory, keep in JSON."""
        cutoff = time.time() - 3600
        with self._lock:
            to_remove = []
            for tid, t in self._tasks.items():
                status = t.get("status")
                if status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED):
                    if t.get("updated_at", 0) < cutoff:
                        to_remove.append(tid)
            for tid in to_remove:
                del self._tasks[tid]
                self._update_counter.pop(tid, None)
                self._log_counter.pop(tid, None)
            if to_remove:
                self._mark_dirty()

    def _cleanup_counters(self, task_id: str):
        """Remove all counter entries for a task."""
        self._update_counter.pop(task_id, None)
        self._log_counter.pop(task_id, None)

    def flush(self):
        """Force immediate save (e.g. on shutdown). Blocks until written."""
        with self._lock:
            try:
                data = json.dumps(self._tasks, ensure_ascii=False, indent=2)
            except Exception:
                return
        TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(TASKS_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, str(TASKS_FILE))

    def stop(self):
        """Stop background worker and flush pending writes."""
        self._stopping = True
        self.flush()

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        now = time.time()
        task = {
            "task_id": task_id,
            "book_id": data.get("book_id", ""),
            "title": data.get("title", ""),
            "isbn": data.get("isbn", ""),
            "ss_code": data.get("ss_code", ""),
            "source": data.get("source", "DX_6.0"),
            "bookmark": data.get("bookmark"),
            "authors": data.get("authors", []),
            "publisher": data.get("publisher", ""),
            "status": STATUS_PENDING,
            "current_step": "",
            "progress": 0,
            "step_detail": "",
            "step_eta": "",
            "logs": [],
            "error": "",
            "report": {},
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._tasks[task_id] = task
            self._mark_dirty()
        return dict(task)

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
        return dict(task) if task else None

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return [dict(t) for t in tasks]

    def update(self, task_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                self._cleanup_counters(task_id)
                return None
            task.update(updates)
            task["updated_at"] = time.time()
            status_changed = "status" in updates or "current_step" in updates
            if status_changed:
                self._mark_dirty()
            else:
                cnt = self._update_counter.get(task_id, 0) + 1
                self._update_counter[task_id] = cnt
                if cnt % 5 == 0:
                    self._mark_dirty()
        return dict(task)

    def update_progress(self, task_id: str, step: str, progress: int, detail: str = "", eta: str = "") -> Optional[Dict[str, Any]]:
        """Update progress fields and persist. Returns updated task or None."""
        return self.update(task_id, {
            "current_step": step,
            "progress": progress,
            "step_detail": detail,
            "step_eta": eta,
        })

    def add_log(self, task_id: str, log_line: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                self._cleanup_counters(task_id)
                return None
            if "logs" not in task:
                task["logs"] = []
            timestamp = time.strftime("%H:%M:%S")
            task["logs"].append(f"[{timestamp}] {log_line}")
            task["updated_at"] = time.time()
            status = task.get("status")
            if status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED):
                if len(task["logs"]) > 20:
                    task["logs"] = task["logs"][-20:]
            elif len(task["logs"]) > 500:
                task["logs"] = task["logs"][-500:]
            cnt = self._log_counter.get(task_id, 0) + 1
            self._log_counter[task_id] = cnt
            if cnt % 10 == 0:
                self._mark_dirty()
        return dict(task)

    def delete(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._cleanup_counters(task_id)
                self._mark_dirty()
                return True
        return False

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._tasks)
            self._tasks.clear()
            self._update_counter.clear()
            self._log_counter.clear()
            self._mark_dirty()
        return count

    def clear_completed(self) -> int:
        with self._lock:
            to_remove = [
                tid for tid, t in self._tasks.items()
                if t.get("status") in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)
            ]
            for tid in to_remove:
                del self._tasks[tid]
                self._cleanup_counters(tid)
            self._mark_dirty()
        return len(to_remove)

    def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task and task.get("status") in (STATUS_PENDING, STATUS_RUNNING, STATUS_PAUSED):
            self.update(task_id, {"status": STATUS_CANCELLED, "_cancelled_at": time.time()})
            with self._lock:
                self._mark_dirty()
            return True
        return False

    def pause(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task and task.get("status") == STATUS_RUNNING:
            self.update(task_id, {"status": STATUS_PAUSED, "_paused_at": time.time()})
            with self._lock:
                self._mark_dirty()
            return True
        return False

    def resume(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task and task.get("status") == STATUS_PAUSED:
            self.update(task_id, {"status": STATUS_RUNNING, "_resumed_at": time.time()})
            with self._lock:
                self._mark_dirty()
            return True
        return False


task_store = TaskStore()
