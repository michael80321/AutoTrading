"""
REST 快照 endpoints
GET /api/snapshot          → 雙池完整快照
GET /api/snapshot/crypto   → 加密池快照
GET /api/snapshot/stock    → 美股池快照
GET /api/evolution/{pool}  → 進化事件時間軸
"""
from fastapi import APIRouter, HTTPException
import AutoTrading.api.state as state

router = APIRouter()


def _require_orchestrator():
    if state.orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")
    return state.orchestrator


@router.get("/snapshot")
async def get_full_snapshot():
    orch = _require_orchestrator()
    return orch.get_full_snapshot()


@router.get("/snapshot/{pool}")
async def get_pool_snapshot(pool: str):
    orch = _require_orchestrator()
    if pool == "crypto":
        return orch.crypto.get_pool_snapshot()
    if pool == "stock":
        return orch.stock.get_pool_snapshot()
    raise HTTPException(status_code=400, detail="pool must be 'crypto' or 'stock'")


@router.get("/evolution/{pool}")
async def get_evolution_events(pool: str):
    orch = _require_orchestrator()
    if pool == "crypto":
        return {"events": orch.crypto.evolution.events[-50:]}
    if pool == "stock":
        return {"events": orch.stock.evolution.events[-50:]}
    raise HTTPException(status_code=400, detail="pool must be 'crypto' or 'stock'")


@router.get("/bots/{pool}/{bot_id}")
async def get_bot_detail(pool: str, bot_id: str):
    orch = _require_orchestrator()
    pool_obj = orch.crypto if pool == "crypto" else orch.stock
    bot = pool_obj.bots.get(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail=f"bot {bot_id} not found")
    return {
        "id": bot.bot_id,
        "name": bot.name,
        "school": pool_obj.bot_schools.get(bot_id),
        "status": pool_obj.evolution.bot_status.get(bot_id),
        "metrics": bot.compute_metrics().__dict__,
        "weight": pool_obj.consensus.get_weight(bot_id, pool_obj.bot_schools.get(bot_id, "")),
        "trade_log_count": len(bot.trade_log),
        "equity_curve": bot.equity_curve[-100:],
    }
