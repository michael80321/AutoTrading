"""
加密池 REST API
GET /api/crypto/snapshot     — 完整池子快照 (bots + portfolio + chat)
GET /api/crypto/bots         — 18 席狀態列表
GET /api/crypto/portfolio    — 倉位 + P&L
GET /api/crypto/chat         — 最新 100 則聊天室訊息
GET /api/crypto/evolution    — 進化事件紀錄
"""
from fastapi import APIRouter, Depends
from .deps import get_orchestrator

router = APIRouter()


@router.get("/snapshot")
async def crypto_snapshot(orchestrator=Depends(get_orchestrator)):
    return orchestrator.crypto.get_pool_snapshot()


@router.get("/bots")
async def crypto_bots(orchestrator=Depends(get_orchestrator)):
    snapshot = orchestrator.crypto.get_pool_snapshot()
    return {"pool": "crypto", "bots": snapshot["bots"]}


@router.get("/portfolio")
async def crypto_portfolio(orchestrator=Depends(get_orchestrator)):
    return orchestrator.crypto.router.get_portfolio_snapshot()["crypto_pool"]


@router.get("/chat")
async def crypto_chat(limit: int = 100, orchestrator=Depends(get_orchestrator)):
    msgs = orchestrator.crypto.chat_messages
    return {"channel": "#crypto-floor", "messages": msgs[-limit:]}


@router.get("/evolution")
async def crypto_evolution(orchestrator=Depends(get_orchestrator)):
    events = orchestrator.crypto.evolution.events
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
