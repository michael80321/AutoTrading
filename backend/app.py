"""
單機後端 — FastAPI 同時提供 API + 內嵌 HTML 儀表板
- GET /                       — 儀表板（前端，純 HTML+JS 輪詢）
- GET /api/crypto/*           — 加密池
- GET /api/stock/*            — 美股池
- GET /api/system/*           — 系統
- GET /health                 — healthcheck（無依賴，永遠秒回）

不再需要：獨立 Next.js 前端、Redis、Postgres、WebSocket。
所有狀態存記憶體；前端每 3 秒輪詢。背景 tick 由 lifespan 啟動。
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .api import crypto_router, stock_router, system_router
from .market_feed import market_tick_loop, stock_tick_loop

logger = logging.getLogger(__name__)

_DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 立刻 yield，所有耗時初始化丟背景，確保 /health 秒回、healthcheck 必過
    app.state.bg_tasks = set()
    app.state.init_done = False
    t = asyncio.create_task(_background_boot(app))
    app.state.bg_tasks.add(t)
    yield
    for task in app.state.bg_tasks:
        task.cancel()


async def _background_boot(app: FastAPI):
    try:
        from .api.deps import get_orchestrator
        orch = get_orchestrator()
        try:
            await asyncio.wait_for(orch.connect_brokers(), timeout=20.0)
        except Exception as e:
            logger.warning(f"broker 連線略過: {e}")
        for coro in [
            orch._tp1_polling_loop(),
            market_tick_loop(orch, interval_seconds=60),
            stock_tick_loop(orch, interval_seconds=300),
        ]:
            task = asyncio.create_task(coro)
            app.state.bg_tasks.add(task)
            task.add_done_callback(app.state.bg_tasks.discard)
        app.state.init_done = True
        logger.info(f"✅ 背景初始化完成，{len(app.state.bg_tasks)} 個任務運行中")
    except Exception as e:
        logger.error(f"背景初始化失敗: {e}", exc_info=True)


app = FastAPI(title="AI Trading Collective", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(crypto_router, prefix="/api/crypto", tags=["Crypto"])
app.include_router(stock_router, prefix="/api/stock", tags=["Stock"])
app.include_router(system_router, prefix="/api/system", tags=["System"])


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return _DASHBOARD


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "init_done": getattr(app.state, "init_done", False),
        "timestamp": datetime.utcnow().isoformat(),
    }
