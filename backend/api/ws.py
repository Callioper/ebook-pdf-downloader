# ==== ws.py ====
# 职责：WebSocket端点，处理客户端连接和任务订阅
# 入口函数：websocket_endpoint()
# 依赖：ws_manager, task_store
# 注意：支持subscribe、unsubscribe和ping消息类型

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ws_manager import ws_manager
from task_store import task_store

router = APIRouter()


@router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_id = uuid.uuid4().hex[:8]
    await ws_manager.connect(websocket, client_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "subscribe":
                task_id = data.get("task_id", "")
                if task_id:
                    ws_manager.subscribe(client_id, task_id)
                    task = task_store.get(task_id)
                    if task:
                        await ws_manager.send_personal(client_id, {
                            "type": "task_update",
                            "task": task,
                        })

            elif msg_type == "unsubscribe":
                task_id = data.get("task_id", "")
                if task_id:
                    ws_manager.unsubscribe(client_id, task_id)

            elif msg_type == "ping":
                await ws_manager.send_personal(client_id, {"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_manager.disconnect(client_id)
