# ==== ws_manager.py ====
# 职责：WebSocket连接管理，处理客户端订阅和消息广播
# 入口函数：ConnectionManager.connect(), disconnect(), subscribe(), broadcast_task()
# 依赖：无
# 注意：支持任务级订阅和全局广播

import asyncio
import json
from typing import Any, Dict, List, Set

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.task_subscriptions: Dict[str, Set[str]] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        for task_id in list(self.task_subscriptions.keys()):
            subs = self.task_subscriptions.get(task_id)
            if subs:
                subs.discard(client_id)
                if not subs:
                    self.task_subscriptions.pop(task_id, None)

    def subscribe(self, client_id: str, task_id: str):
        if task_id not in self.task_subscriptions:
            self.task_subscriptions[task_id] = set()
        self.task_subscriptions[task_id].add(client_id)

    def unsubscribe(self, client_id: str, task_id: str):
        subs = self.task_subscriptions.get(task_id)
        if subs:
            subs.discard(client_id)

    async def send_personal(self, client_id: str, message: Dict[str, Any]):
        ws = self.active_connections.get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(client_id)

    async def broadcast_task(self, task_id: str, message: Dict[str, Any]):
        subs = self.task_subscriptions.get(task_id, set())
        for client_id in list(subs):
            await self.send_personal(client_id, message)

    async def broadcast_all(self, message: Dict[str, Any]):
        for client_id in list(self.active_connections.keys()):
            await self.send_personal(client_id, message)


ws_manager = ConnectionManager()
