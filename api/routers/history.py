"""
GET /api/history/signals?pool=crypto&limit=100
GET /api/history/trades?pool=crypto&limit=100
"""
from fastapi import APIRouter, Query
from sqlalchemy import text
from db.database import AsyncSessionLocal

router = APIRouter()

@router.get("/history/signals")
async def get_signal_history(pool: str = "crypto", limit: int = Query(100, le=500)):
    if AsyncSessionLocal is None:
        return {"signals": [], "note": "DB not configured"}
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT ts, bot_id, bot_name, school, symbol, side, entry_price, confidence "
                 "FROM signals WHERE pool = :pool ORDER BY ts DESC LIMIT :limit"),
            {"pool": pool, "limit": limit}
        )
        rows = [dict(r._mapping) for r in result]
    return {"signals": rows}

@router.get("/history/trades")
async def get_trade_history(pool: str = "crypto", limit: int = Query(100, le=500)):
    if AsyncSessionLocal is None:
        return {"trades": [], "note": "DB not configured"}
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT ts, bot_id, symbol, side, entry_price, exit_price, pnl, hold_bars "
                 "FROM trades WHERE pool = :pool ORDER BY ts DESC LIMIT :limit"),
            {"pool": pool, "limit": limit}
        )
        rows = [dict(r._mapping) for r in result]
    return {"trades": rows}
