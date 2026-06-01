"""
加密池 REST API
GET /api/crypto/snapshot     — 完整池子快照 (bots + portfolio + chat)
GET /api/crypto/bots         — 18 席狀態列表
GET /api/crypto/portfolio    — 倉位 + P&L + 即時餘額 + 開放倉位明細
GET /api/crypto/positions    — 開放倉位列表
GET /api/crypto/chat         — 最新 100 則聊天室訊息
GET /api/crypto/evolution    — 進化事件紀錄
GET /api/crypto/backtest     — 對所有 18 席跑 walk-forward 回測（約 10-30 秒）
"""
import asyncio
from fastapi import APIRouter, Depends
from .deps import get_orchestrator

router = APIRouter()


@router.get("/snapshot")
async def crypto_snapshot(orchestrator=Depends(get_orchestrator)):
    # 同時拉即時 Binance 餘額更新 crypto_pool
    await orchestrator.crypto.router.fetch_binance_balance()
    return orchestrator.crypto.get_pool_snapshot()


@router.get("/bots")
async def crypto_bots(orchestrator=Depends(get_orchestrator)):
    snapshot = orchestrator.crypto.get_pool_snapshot()
    return {"pool": "crypto", "bots": snapshot["bots"]}


@router.get("/portfolio")
async def crypto_portfolio(orchestrator=Depends(get_orchestrator)):
    # 餘額由背景 tick loop 即時更新，這裡直接讀快取
    return orchestrator.crypto.router.get_portfolio_snapshot()["crypto_pool"]


@router.get("/positions")
async def crypto_positions(orchestrator=Depends(get_orchestrator)):
    router_ = orchestrator.crypto.router
    positions = [
        router_._order_to_dict(o)
        for o in router_.open_orders.values()
        if o.pool == "crypto"
    ]
    return {"positions": positions, "count": len(positions)}


@router.get("/chat")
async def crypto_chat(limit: int = 100, orchestrator=Depends(get_orchestrator)):
    msgs = orchestrator.crypto.chat_messages
    return {"channel": "#crypto-floor", "messages": msgs[-limit:] if limit > 0 else []}


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


@router.get("/signal-debug")
async def crypto_signal_debug(orchestrator=Depends(get_orchestrator)):
    """
    診斷端點：即時跑一輪訊號生成，回傳每個 bot 的狀態和共識拒絕原因。
    用於排查「為何沒開單」。
    """
    import httpx
    import pandas as pd
    from ..market_feed import fetch_ohlcv, CRYPTO_SYMBOLS, TIMEFRAME, OHLCV_LIMIT

    # 抓即時市場數據
    async with httpx.AsyncClient() as client:
        market_data = {}
        for symbol in CRYPTO_SYMBOLS:
            df = await fetch_ohlcv(client, symbol, TIMEFRAME, OHLCV_LIMIT)
            if df is not None and len(df) >= 200:
                market_data[symbol] = df

    if not market_data:
        return {"error": "無法取得市場數據"}

    pool = orchestrator.crypto
    bot_results = []
    all_signals = []

    for bot_id, bot in pool.bots.items():
        bot_sigs = []
        for symbol, data in market_data.items():
            try:
                sig = bot.signal(data, {"symbol": symbol})
                if sig:
                    bot_sigs.append({
                        "symbol": sig.symbol, "side": sig.side,
                        "confidence": round(sig.confidence, 3),
                        "sl_dist_pct": round(abs(sig.entry_price - sig.stop_loss) / sig.entry_price * 100, 2),
                    })
                    all_signals.append(sig)
            except Exception as e:
                bot_sigs.append({"symbol": symbol, "error": str(e)})

        metrics = bot.compute_metrics()
        bot_results.append({
            "id": bot_id, "name": bot.name, "school": pool.bot_schools.get(bot_id),
            "status": pool.evolution.bot_status.get(bot_id),
            "win_rate": metrics.win_rate, "trades": metrics.total_trades,
            "signals_this_tick": bot_sigs,
        })

    # 跑共識
    bot_winrates = {bid: bot.compute_metrics().win_rate for bid, bot in pool.bots.items()}
    consensus_results = {}
    for symbol in market_data:
        sym_sigs = [s for s in all_signals if s.symbol == symbol]
        long_s = [s for s in sym_sigs if s.side == "LONG"]
        short_s = [s for s in sym_sigs if s.side == "SHORT"]
        consensus = pool.consensus.aggregate(all_signals, bot_winrates, pool.config.capital.crypto_pool_total, symbol)
        consensus_results[symbol] = {
            "total_signals": len(sym_sigs),
            "long_signals": len(long_s),
            "short_signals": len(short_s),
            "long_schools": list({s.school for s in long_s}),
            "short_schools": list({s.school for s in short_s}),
            "approved": consensus.approved if consensus else False,
            "rationale": consensus.rationale if consensus else "未通過共識",
        }

    return {
        "symbols": list(market_data.keys()),
        "total_signals": len(all_signals),
        "bots": bot_results,
        "consensus": consensus_results,
        "thresholds": {
            "min_aligned_schools": pool.consensus.min_aligned_schools,
            "min_total_weight": pool.consensus.min_total_weight,
            "min_backtest_winrate": pool.consensus.min_backtest_winrate,
        },
    }


@router.get("/backtest")
async def crypto_backtest(symbol: str = "BTCUSDT", orchestrator=Depends(get_orchestrator)):
    """
    對加密池 18 席分析師跑 walk-forward 回測。
    預設用 BTCUSDT 的 1000 根 1H K 棒（約 41 天）。
    回測在 worker thread 執行，不阻塞事件循環。
    """
    import httpx
    import pandas as pd

    # 抓 1000 根 1H K 棒
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "1h", "limit": 1000},
            timeout=15.0,
        )
    if resp.status_code != 200:
        return {"error": f"Binance kline 抓取失敗: {resp.status_code}"}

    raw = resp.json()
    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)

    from autotrading.backtest.walkforward import BacktestEngine
    engine = BacktestEngine()

    def _run_all_bots():
        results = []
        for bot_id, bot in orchestrator.crypto.bots.items():
            try:
                r = engine.run(bot, df, walk_forward_segments=4)
                results.append({
                    "bot_id": bot_id,
                    "name": bot.name,
                    "school": getattr(bot, "SCHOOL", ""),
                    "total_trades": r.total_trades,
                    "win_rate": round(r.win_rate * 100, 1),
                    "sharpe": r.sharpe,
                    "max_drawdown_pct": round(r.max_drawdown * 100, 1),
                    "expectancy": r.expectancy,
                    "final_equity": r.final_equity,
                    "oos_consistency": round(r.out_of_sample_consistency * 100, 0),
                    "passed": r.passed(min_winrate=0.45, min_sharpe=0.5),
                })
            except Exception as e:
                results.append({
                    "bot_id": bot_id,
                    "name": bot.name,
                    "school": getattr(bot, "SCHOOL", ""),
                    "error": str(e),
                })
        return results

    results = await asyncio.to_thread(_run_all_bots)

    passed = [r for r in results if r.get("passed")]
    return {
        "symbol": symbol,
        "candles": len(df),
        "period_hours": len(df),
        "bots_passed": len(passed),
        "bots_total": len(results),
        "results": sorted(results, key=lambda x: x.get("win_rate", 0), reverse=True),
    }
