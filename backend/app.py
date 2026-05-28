"""
FastAPI 後端 — 雙池 AI 交易系統 API Server
- REST API: /api/crypto/*, /api/stock/*, /api/system/*
- WebSocket: /ws/crypto, /ws/stock (即時 chat + 信號推播)
- Redis pub/sub: 池間警示廣播
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .redis_bus import RedisBus
from .ws_manager import ConnectionManager
from .api import crypto_router, stock_router, system_router

logger = logging.getLogger(__name__)

redis_bus = RedisBus(url=os.getenv("REDIS_URL", "redis://localhost:6379"))
ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_bus.connect()
    asyncio.create_task(redis_bus.subscribe_and_forward(ws_manager))
    logger.info("✅ Redis bus 已連線")
    yield
    await redis_bus.disconnect()


app = FastAPI(
    title="AI Trading Collective API",
    version="1.0.0",
    description="雙池 36 席分析師交易系統",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(crypto_router, prefix="/api/crypto", tags=["Crypto Pool"])
app.include_router(stock_router, prefix="/api/stock", tags=["Stock Pool"])
app.include_router(system_router, prefix="/api/system", tags=["System"])


@app.websocket("/ws/{pool}")
async def websocket_endpoint(websocket: WebSocket, pool: Literal["crypto", "stock"]):
    await ws_manager.connect(websocket, pool)
    try:
        while True:
            # 保持連線,等待客戶端 ping
            data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            if data == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, asyncio.TimeoutError):
        ws_manager.disconnect(websocket, pool)


@app.get("/health")
async def health():
    redis_ok = await redis_bus.ping()
    return {
        "status": "ok",
        "redis": "ok" if redis_ok else "unavailable",
        "timestamp": datetime.utcnow().isoformat(),
    }
