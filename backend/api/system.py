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


@router.get("/funding")
async def funding_rates():
    """查目前 4 個交易對的即時資金費率，確認套利分析師有資料可用"""
    import httpx
    from autotrading.backend.market_feed import fetch_funding_rate, CRYPTO_SYMBOLS
    out = {}
    async with httpx.AsyncClient() as c:
        for sym in CRYPTO_SYMBOLS:
            fr = await fetch_funding_rate(c, sym, limit=3)
            if fr is not None and len(fr) > 0:
                latest = float(fr.iloc[-1])
                out[sym] = {
                    "funding_rate": round(latest, 6),
                    "annualized_pct": round(latest * 3 * 365 * 100, 2),  # 每日 3 次 × 365
                    "last_3": [round(float(x), 6) for x in fr.tail(3).tolist()],
                }
            else:
                out[sym] = {"error": "no data"}
    return out


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


@router.get("/debug")
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

    # 直接嘗試抓合約餘額，回傳結果或錯誤
    balance_result = None
    balance_error = None
    if exchange is not None:
        try:
            bal = await exchange.fetch_balance({"type": "future"})
            usdt = bal.get("USDT", {})
            balance_result = {
                "free": usdt.get("free"),
                "used": usdt.get("used"),
                "total": usdt.get("total"),
            }
        except Exception as e:
            balance_error = str(e)

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
        "binance_reachable": binance_ok,
        "futures_balance": balance_result,
        "futures_balance_error": balance_error,
        "ibkr_client_connected": orchestrator.stock.router.ibkr is not None,
    }


@router.get("/test-order")
async def test_order(
    symbol: str = "TRXUSDT",
    confirm: bool = False,
    orchestrator=Depends(get_orchestrator),
):
    """
    驗證合約下單路徑。
    confirm=false（預設）：只模擬，不下真實訂單。
    confirm=true：下一張最小金額合約單後立刻平倉，驗證完整路徑。
    建議先用 confirm=false 確認參數無誤，再用 confirm=true。
    """
    exchange = orchestrator.crypto.router.binance
    if exchange is None:
        return {"ok": False, "error": "exchange client 未初始化，請確認 BINANCE_API_KEY 已設定"}

    try:
        # 1. 抓目前價格與精度
        await exchange.load_markets()
        ticker = await exchange.fetch_ticker(symbol)
        price = float(ticker["last"])
        market = exchange.markets.get(symbol, {})
        amount_precision = market.get("precision", {}).get("amount", 1)

        # 計算最小下單量（目標名目 ~10 USDT）
        target_notional = 10.0
        raw_qty = target_notional / price
        # 無條件進位到精度
        import math
        step = 10 ** (-amount_precision)
        qty = math.ceil(raw_qty / step) * step
        qty = round(qty, amount_precision)
        notional = round(qty * price, 2)

        plan = {
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "notional_usdt": notional,
            "amount_precision": amount_precision,
            "steps": [
                f"BUY MARKET {qty} {symbol} (進場，名目 ~${notional} USDT)",
                f"SELL MARKET {qty} {symbol} reduceOnly=True (立刻平倉)",
            ],
        }

        if not confirm:
            return {
                "ok": True,
                "dry_run": True,
                "message": "模擬模式，未下單。加上 ?confirm=true 執行真實測試。",
                **plan,
            }

        # 2. 真實下單：開倉
        entry = await exchange.create_market_order(symbol, "buy", qty)
        entry_price = float(entry.get("average") or entry.get("price") or price)

        # 3. 立刻平倉
        close = await exchange.create_market_order(
            symbol, "sell", qty, None, {"reduceOnly": True}
        )
        close_price = float(close.get("average") or close.get("price") or price)

        pnl = (close_price - entry_price) * qty
        fee = notional * 0.0004 * 2  # taker * 來回

        return {
            "ok": True,
            "dry_run": False,
            "symbol": symbol,
            "qty": qty,
            "entry_price": entry_price,
            "close_price": close_price,
            "gross_pnl": round(pnl, 4),
            "estimated_fee": round(fee, 4),
            "net_pnl": round(pnl - fee, 4),
            "entry_order_id": entry.get("id"),
            "close_order_id": close.get("id"),
            "message": "✅ 下單與平倉成功，合約路徑驗證通過",
        }

    except Exception as e:
        return {"ok": False, "error": str(e), "symbol": symbol}

