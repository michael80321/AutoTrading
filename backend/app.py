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
from .market_feed import market_tick_loop, stock_tick_loop

logger = logging.getLogger(__name__)

redis_bus = RedisBus(url=os.getenv("REDIS_URL", "redis://localhost:6379"))
ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_bus.connect()
    asyncio.create_task(redis_bus.subscribe_and_forward(ws_manager))
    logger.info("✅ Redis bus 已連線")
    # 初始化協調器並連接 brokers
    from .api.deps import get_orchestrator
    orch = get_orchestrator()
    await orch.connect_brokers()
    # 保留強引用，防止 asyncio GC 在任務執行前回收
    _bg_tasks = set()
    for coro in [
        orch._tp1_polling_loop(),
        market_tick_loop(orch, redis_bus, interval_seconds=60),
        stock_tick_loop(orch, redis_bus, interval_seconds=300),
    ]:
        t = asyncio.create_task(coro)
        _bg_tasks.add(t)
        t.add_done_callback(_bg_tasks.discard)
    app.state.bg_tasks = _bg_tasks  # 掛到 app.state 確保生命週期夠長
    logger.info(f"✅ 已啟動 {len(_bg_tasks)} 個背景任務")
    yield
    for t in _bg_tasks:
        t.cancel()
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
    try:
        redis_ok = await asyncio.wait_for(redis_bus.ping(), timeout=2.0)
    except (asyncio.TimeoutError, Exception):
        redis_ok = False
    return {
        "status": "ok",
        "redis": "ok" if redis_ok else "unavailable",
        "timestamp": datetime.utcnow().isoformat(),
    }
