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
    # 關鍵：lifespan 必須立刻 yield，讓 /health 馬上可用，避免 Railway healthcheck 逾時回滾。
    # 所有耗時的初始化（Redis、broker、36 席 bot、tick loop）都丟到背景任務，不阻塞啟動。
    app.state.bg_tasks = set()
    app.state.init_done = False
    boot = asyncio.create_task(_background_boot(app))
    app.state.bg_tasks.add(boot)
    yield
    for t in app.state.bg_tasks:
        t.cancel()
    try:
        await redis_bus.disconnect()
    except Exception:
        pass


async def _background_boot(app: FastAPI):
    """在 app 已健康後才執行的初始化流程，任何步驟失敗都不影響服務存活。"""
    # 1. Redis（連不上也沒關係，降級為記憶體模式）
    try:
        await asyncio.wait_for(redis_bus.connect(), timeout=10.0)
        t = asyncio.create_task(redis_bus.subscribe_and_forward(ws_manager))
        app.state.bg_tasks.add(t)
        t.add_done_callback(app.state.bg_tasks.discard)
        logger.info("✅ Redis bus 已連線")
    except Exception as e:
        logger.warning(f"Redis 初始化失敗（降級運行）: {e}")

    # 2. 協調器 + broker
    try:
        from .api.deps import get_orchestrator
        orch = get_orchestrator()
        try:
            await asyncio.wait_for(orch.connect_brokers(), timeout=20.0)
        except Exception as e:
            logger.warning(f"broker 連線略過: {e}")

        # 3. 背景任務：TP1 輪詢 + 加密/美股 tick loop
        for coro in [
            orch._tp1_polling_loop(),
            market_tick_loop(orch, redis_bus, interval_seconds=60),
            stock_tick_loop(orch, redis_bus, interval_seconds=300),
        ]:
            t = asyncio.create_task(coro)
            app.state.bg_tasks.add(t)
            t.add_done_callback(app.state.bg_tasks.discard)
        app.state.init_done = True
        logger.info(f"✅ 背景初始化完成，{len(app.state.bg_tasks)} 個任務運行中")
    except Exception as e:
        logger.error(f"背景初始化失敗: {e}", exc_info=True)


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
    # 只確認 HTTP server 存活，絕不依賴 Redis/broker，確保 Railway healthcheck 永遠通過
    return {
        "status": "ok",
        "init_done": getattr(app.state, "init_done", False),
        "timestamp": datetime.utcnow().isoformat(),
    }
