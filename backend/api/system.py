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


@router.get("/test-feed")
async def test_feed():
    """直接測試 Binance OHLCV 抓取，回傳原始結果用於診斷"""
    import httpx
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": "1h", "limit": "5"}
    try:
        async with httpx.AsyncClient() as c:
            resp = await c.get(url, params=params, timeout=10.0)
            return {
                "status_code": resp.status_code,
                "body": resp.json(),
                "error": None,
            }
    except Exception as e:
        return {"status_code": None, "body": None, "error": str(e)}


@router.get("/ip")
async def server_ip():
    """查詢 Railway 伺服器目前的對外 IP"""
    import httpx
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get("https://api.ipify.org?format=json", timeout=8.0)
            ip = r.json().get("ip", "unknown")
        return {
            "outbound_ip": ip,
            "note": "此 IP 為 Railway 容器目前對外 IP，重新部署後可能更換。建議 Binance API 改為不設 IP 限制，或改用 Bybit。",
        }
    except Exception as e:
        return {"outbound_ip": None, "error": str(e)}


async def debug_status(orchestrator=Depends(get_orchestrator)):
    """診斷端點 — 顯示 tick loop 狀態"""
    import httpx
    binance_ok = False
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get("https://api.binance.com/api/v3/ping", timeout=5.0)
            binance_ok = r.status_code == 200
    except Exception:
        pass

    exchange = orchestrator.crypto.router.binance
    exchange_name = type(exchange).__name__ if exchange else "none"
    last_tick = getattr(orchestrator.crypto, "_last_tick_at", None)
    return {
        "crypto_bots": len(orchestrator.crypto.bots),
        "stock_bots": len(orchestrator.stock.bots),
        "crypto_chat_messages": len(orchestrator.crypto.chat_messages),
        "stock_chat_messages": len(orchestrator.stock.chat_messages),
        "crypto_last_tick_at": last_tick.isoformat() if last_tick else None,
        "crypto_open_positions": len(orchestrator.crypto.router.open_orders),
        "crypto_pool_usdt": orchestrator.crypto.router.crypto_pool,
        "exchange_client": exchange_name,
        "exchange_connected": exchange is not None,
        "bybit_api_reachable": binance_ok,
        "ibkr_client_connected": orchestrator.stock.router.ibkr is not None,
    }
