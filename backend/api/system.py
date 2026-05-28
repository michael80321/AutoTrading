"""
系統級 REST API
GET /api/system/snapshot     — 完整雙池快照
GET /api/system/risk         — 帳戶級風控狀態
GET /api/system/warnings     — 跨池警示
POST /api/system/halt        — 緊急熔斷 (需要 admin token)
"""
import os
from fastapi import APIRouter, Depends, HTTPException, Header
from .deps import get_orchestrator

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me-in-production")


def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")


@router.get("/snapshot")
async def full_snapshot(orchestrator=Depends(get_orchestrator)):
    return orchestrator.get_full_snapshot()


@router.get("/risk")
async def risk_status(orchestrator=Depends(get_orchestrator)):
    cfg = orchestrator.config
    crypto_pnl = sum(o.realized_pnl for o in orchestrator.crypto.router.closed_orders)
    stock_pnl = sum(o.realized_pnl for o in orchestrator.stock.router.closed_orders)
    total_capital = cfg.capital.crypto_pool_total + cfg.capital.stock_pool_total
    total_pnl = crypto_pnl + stock_pnl
    total_dd = total_pnl / total_capital if total_pnl < 0 else 0.0

    return {
        "total_capital": total_capital,
        "total_realized_pnl": round(total_pnl, 2),
        "total_drawdown_pct": round(total_dd * 100, 2),
        "max_drawdown_limit_pct": cfg.account_max_drawdown_pct * 100,
        "halted": abs(total_dd) >= cfg.account_max_drawdown_pct,
        "crypto_pnl": round(crypto_pnl, 2),
        "stock_pnl": round(stock_pnl, 2),
    }


@router.get("/warnings")
async def cross_pool_warnings(orchestrator=Depends(get_orchestrator)):
    return {"warnings": orchestrator.cross_pool_warnings}


@router.post("/halt", dependencies=[Depends(verify_admin)])
async def emergency_halt(orchestrator=Depends(get_orchestrator)):
    orchestrator.crypto.router.open_orders.clear()
    orchestrator.stock.router.open_orders.clear()
    return {"halted": True, "message": "所有新部位已暫停"}
