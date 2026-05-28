"""
FastAPI 主應用 — 雙池 AI 交易系統後端
endpoints:
  GET  /health
  GET  /api/snapshot
  GET  /api/snapshot/{pool}   pool = crypto | stock
  WS   /ws/chat/{pool}        pool = crypto | stock
  WS   /ws/signals
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from AutoTrading.main import DualPoolOrchestrator
from AutoTrading.config.system import SystemConfig
import AutoTrading.api.state as state
from AutoTrading.api.routers import snapshot as snapshot_router
from AutoTrading.api.routers import history as history_router
from AutoTrading.data.feed_manager import FeedManager
from db.database import init_db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ─── lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 啟動 AI Trading Collective 後端")
    tick_task = None

    # Redis（失敗しても継続）
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        state.redis_client = aioredis.from_url(redis_url, decode_responses=True)
        await state.redis_client.ping()
        logger.info(f"✅ Redis 已連線: {redis_url[:40]}...")
    except Exception as e:
        logger.warning(f"⚠️  Redis 連線失敗 ({e}),WebSocket 功能降級")

    # Database（失敗しても継続）
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        try:
            init_db(db_url)
            logger.info("✅ 資料庫連線初始化完成")
        except Exception as e:
            logger.warning(f"⚠️  DB 初始化失敗 ({e}),跳過")

    # Orchestrator（失敗しても継続）
    try:
        state.orchestrator = DualPoolOrchestrator(SystemConfig())
        state.orchestrator.initialize()
        logger.info("✅ DualPoolOrchestrator 初始化完成")
    except Exception as e:
        logger.error(f"❌ Orchestrator 初始化失敗: {e}", exc_info=True)

    # FeedManager tick loop（失敗しても継続）
    if state.orchestrator and state.redis_client:
        try:
            feed_mgr = FeedManager(state.orchestrator, state.redis_client)
            tick_task = asyncio.create_task(feed_mgr.run_forever())
            logger.info("✅ FeedManager 啟動")
        except Exception as e:
            logger.error(f"❌ FeedManager 啟動失敗: {e}", exc_info=True)

    yield

    # ── shutdown ──
    if tick_task:
        tick_task.cancel()
    if state.redis_client:
        try:
            await state.redis_client.aclose()
        except Exception:
            pass
    logger.info("🛑 後端已關閉")


# ─── app ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Trading Collective",
    version="2.0.0",
    description="雙池 36 席 AI 分析師系統",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 正式上線後改為 Vercel domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(snapshot_router.router, prefix="/api")
app.include_router(history_router.router, prefix="/api")


# ─── health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "redis": state.redis_client is not None,
        "orchestrator": state.orchestrator is not None,
        "crypto_bots": len(state.orchestrator.crypto.bots) if state.orchestrator else 0,
        "stock_bots": len(state.orchestrator.stock.bots) if state.orchestrator else 0,
    }


# ─── WebSocket: 聊天室 ────────────────────────────────────────────────────────

@app.websocket("/ws/chat/{pool}")
async def ws_chat(websocket: WebSocket, pool: str):
    """
    訂閱指定池的聊天室訊息流。
    pool: "crypto" → channel: chat:crypto-floor
          "stock"  → channel: chat:equities-floor
    """
    if pool not in ("crypto", "stock"):
        await websocket.close(code=4000, reason="pool must be crypto or stock")
        return

    await websocket.accept()
    channel = f"chat:{'crypto-floor' if pool == 'crypto' else 'equities-floor'}"
    pubsub = state.redis_client.pubsub()
    await pubsub.subscribe(channel)
    logger.info(f"WS client joined {channel}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


# ─── WebSocket: 信號串流 ──────────────────────────────────────────────────────

@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    """訂閱全部池的信號串流 (兩池都推送)"""
    await websocket.accept()
    pubsub = state.redis_client.pubsub()
    await pubsub.subscribe("signals:crypto", "signals:stock")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe("signals:crypto", "signals:stock")
        await pubsub.aclose()
