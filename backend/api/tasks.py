# -*- coding: utf-8 -*-
# ==== tasks.py ====
# 职责：任务管理API路由，处理任务的创建、查询、删除和控制
# 入口函数：list_tasks(), create_task(), start_task(), cancel_task(), retry_task()
# 依赖：task_store, ws_manager, config, engine.pipeline
# 注意：支持后台任务执行和WebSocket通知

import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from task_store import task_store, STATUS_PENDING, STATUS_RUNNING, STATUS_PAUSED, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED
from ws_manager import ws_manager
from config import get_config

router = APIRouter(prefix="/api/v1/tasks")


class TaskCreateRequest(BaseModel):
    book_id: str = ""
    title: str = ""
    isbn: str = ""
    ss_code: str = ""
    source: str = "DX_6.0"
    bookmark: Optional[str] = None
    authors: List[str] = []
    publisher: str = ""


@router.get("")
async def list_tasks():
    tasks = task_store.list_all()
    # Strip logs to last 5 for list view (reduces payload ~90%)
    for t in tasks:
        if isinstance(t.get("logs"), list) and len(t["logs"]) > 5:
            t["logs"] = t["logs"][-5:]
    return {"tasks": tasks}


@router.post("")
async def create_task(body: TaskCreateRequest):
    task = task_store.create(body.model_dump())
    await ws_manager.broadcast_all({"type": "task_created", "task": task})
    return task


@router.delete("")
async def clear_all_tasks():
    count = task_store.clear_all()
    await ws_manager.broadcast_all({"type": "tasks_cleared", "count": count})
    return {"ok": True, "count": count}


@router.delete("/completed")
async def clear_completed_tasks():
    count = task_store.clear_completed()
    return {"ok": True, "count": count}


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    task = task_store.get(task_id)
    if task and task.get("status") == STATUS_RUNNING:
        raise HTTPException(status_code=400, detail="Cannot delete a running task")
    ok = task_store.delete(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    await ws_manager.broadcast_task(task_id, {"type": "task_deleted", "task_id": task_id})
    return {"ok": True}


@router.get("/{task_id}/report")
async def get_task_report(task_id: str):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.get("report", {})


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    ok = task_store.cancel(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Task cannot be cancelled")
    task_store.update(task_id, {"status": STATUS_CANCELLED})
    await ws_manager.broadcast_task(task_id, {
        "type": "task_update",
        "task_id": task_id,
        "status": STATUS_CANCELLED,
    })
    return {"ok": True}


@router.post("/{task_id}/pause")
async def pause_task(task_id: str):
    ok = task_store.pause(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Task cannot be paused")
    await ws_manager.broadcast_task(task_id, {
        "type": "task_update",
        "task_id": task_id,
        "status": STATUS_PAUSED,
    })
    return {"ok": True}


@router.post("/{task_id}/resume")
async def resume_task(task_id: str):
    ok = task_store.resume(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Task cannot be resumed")
    await ws_manager.broadcast_task(task_id, {
        "type": "task_update",
        "task_id": task_id,
        "status": STATUS_RUNNING,
    })
    return {"ok": True}


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, background_tasks: BackgroundTasks):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    from engine.pipeline import run_pipeline
    task_store.update(task_id, {
        "status": STATUS_PENDING,
        "current_step": "",
        "progress": 0,
        "error": "",
        "logs": [],
        "report": {},
    })
    await ws_manager.broadcast_task(task_id, {
        "type": "task_retry",
        "task_id": task_id,
    })
    background_tasks.add_task(run_pipeline, task_id)
    return {"ok": True, "task_id": task_id}


@router.post("/{task_id}/start")
async def start_task(task_id: str, background_tasks: BackgroundTasks):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") == STATUS_RUNNING:
        raise HTTPException(status_code=400, detail="Task is already running")

    from engine.pipeline import run_pipeline
    task_store.update(task_id, {
        "status": STATUS_PENDING,
        "current_step": "starting",
        "progress": 0,
        "logs": [],
        "error": "",
        "report": {},
    })
    background_tasks.add_task(run_pipeline, task_id)
    return {"ok": True, "task_id": task_id}


@router.get("/{task_id}/open")
async def open_pdf(task_id: str):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    report = task.get("report", {})
    pdf_path = report.get("pdf_path", "") or report.get("output_file", "")
    if pdf_path and os.path.exists(pdf_path):
        try:
            if os.name == "nt":
                os.startfile(pdf_path)
            else:
                subprocess.run(["xdg-open", pdf_path])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "message": str(e)}
    return {"ok": False, "message": "PDF not found"}


@router.get("/{task_id}/open-folder")
async def open_folder(task_id: str):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    config = get_config()
    output_dir = config.get("finished_dir", "")
    if output_dir and os.path.exists(output_dir):
        try:
            if os.name == "nt":
                os.startfile(output_dir)
            else:
                subprocess.run(["xdg-open", output_dir])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "message": str(e)}
    return {"ok": False, "message": "Folder not found"}


class ConfirmDownloadRequest(BaseModel):
    confirm: bool = True
    book_id: str = ""  # ZL book ID for the selected candidate
    book_hash: str = ""  # ZL book hash for the selected candidate


@router.post("/{task_id}/confirm-download")
async def confirm_download(task_id: str, body: ConfirmDownloadRequest):
    """用户确认/拒绝消耗下载额度（Z-Library 等），可选指定选择的条目"""
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    update = {"_zl_confirm": body.confirm}
    if body.book_id and body.book_hash:
        update["_zl_confirm_selection"] = {"id": body.book_id, "hash": body.book_hash}
    task_store.update(task_id, update)
    logger = logging.getLogger(__name__)
    if body.book_id:
        logger.info(f"User selected book {body.book_id} for task {task_id}")
    logger.info(f"User {'confirmed' if body.confirm else 'declined'} download for task {task_id}")
    return {"ok": True, "confirm": body.confirm}
