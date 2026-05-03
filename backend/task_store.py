import json
import os
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from config import get_config

TASKS_FILE = Path(__file__).resolve().parent.parent / "tasks.json"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
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
        self._load()

    def _load(self):
        if TASKS_FILE.exists():
            try:
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    self._tasks = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._tasks = {}

    def _save(self):
        TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(self._tasks, f, ensure_ascii=False, indent=2)

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
            "logs": [],
            "error": "",
            "report": {},
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._tasks[task_id] = task
            self._save()
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
                return None
            task.update(updates)
            task["updated_at"] = time.time()
            self._save()
        return dict(task)

    def add_log(self, task_id: str, log_line: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if "logs" not in task:
                task["logs"] = []
            timestamp = time.strftime("%H:%M:%S")
            task["logs"].append(f"[{timestamp}] {log_line}")
            task["updated_at"] = time.time()
            self._save()
        return dict(task)

    def delete(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._save()
                return True
        return False

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._tasks)
            self._tasks.clear()
            self._save()
        return count

    def clear_completed(self) -> int:
        with self._lock:
            to_remove = [
                tid for tid, t in self._tasks.items()
                if t.get("status") in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)
            ]
            for tid in to_remove:
                del self._tasks[tid]
            self._save()
        return len(to_remove)

    def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task and task.get("status") in (STATUS_PENDING, STATUS_RUNNING):
            self.update(task_id, {"status": STATUS_CANCELLED})
            return True
        return False


task_store = TaskStore()
