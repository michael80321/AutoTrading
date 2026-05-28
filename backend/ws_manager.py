"""
WebSocket 連線管理器 — 雙池各自維護一組連線
"""
import json
import logging
from typing import Literal

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._pools: dict[str, list[WebSocket]] = {"crypto": [], "stock": []}

    async def connect(self, websocket: WebSocket, pool: str):
        await websocket.accept()
        self._pools.setdefault(pool, []).append(websocket)
        logger.debug(f"WS 連線: {pool} 共 {len(self._pools[pool])} 個")

    def disconnect(self, websocket: WebSocket, pool: str):
        conns = self._pools.get(pool, [])
        if websocket in conns:
            conns.remove(websocket)

    async def broadcast(self, pool: str, payload: dict):
        conns = self._pools.get(pool, [])[:]
        dead = []
        for ws in conns:
            try:
                await ws.send_text(json.dumps(payload, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, pool)

    async def broadcast_all(self, payload: dict):
        for pool in self._pools:
            await self.broadcast(pool, payload)

    def connection_count(self, pool: str) -> int:
        return len(self._pools.get(pool, []))
