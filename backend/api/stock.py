"""
美股池 REST API
GET /api/stock/snapshot      — 完整池子快照
GET /api/stock/bots          — 18 席狀態列表
GET /api/stock/portfolio     — 倉位 + P&L
GET /api/stock/chat          — 最新 100 則聊天室訊息
GET /api/stock/evolution     — 進化事件紀錄
"""
from fastapi import APIRouter, Depends
from .deps import get_orchestrator

router = APIRouter()


@router.get("/snapshot")
async def stock_snapshot(orchestrator=Depends(get_orchestrator)):
    return orchestrator.stock.get_pool_snapshot()


@router.get("/bots")
async def stock_bots(orchestrator=Depends(get_orchestrator)):
    snapshot = orchestrator.stock.get_pool_snapshot()
    return {"pool": "stock", "bots": snapshot["bots"]}


@router.get("/portfolio")
async def stock_portfolio(orchestrator=Depends(get_orchestrator)):
    return orchestrator.stock.router.get_portfolio_snapshot()["stock_pool"]


@router.get("/chat")
async def stock_chat(limit: int = 100, orchestrator=Depends(get_orchestrator)):
    msgs = orchestrator.stock.chat_messages
    return {"channel": "#equities-floor", "messages": msgs[-limit:]}


@router.get("/evolution")
async def stock_evolution(orchestrator=Depends(get_orchestrator)):
    events = orchestrator.stock.evolution.events
    return {
        "events": [
            {
                "timestamp": e.timestamp.isoformat(),
                "bot_name": e.bot_name,
                "action": e.action,
                "note": e.note,
            }
            for e in events[-50:]
        ]
    }
