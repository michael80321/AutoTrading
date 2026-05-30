"""
市場數據背景餵送
- 加密池：每 60 秒從 Binance 公開 API 抓 OHLCV（新加坡節點可連）
- 美股池：每 300 秒用 yfinance 抓 OHLCV
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
OHLCV_LIMIT = 300
TIMEFRAME = "1h"  # Binance klines interval 格式

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"


async def fetch_funding_rate(client: httpx.AsyncClient, symbol: str, limit: int = 100) -> pd.Series | None:
    """抓 Binance 永續合約資金費率歷史（每 8 小時一筆），回傳以時間為索引的 Series。"""
    try:
        resp = await client.get(
            BINANCE_FUNDING_URL,
            params={"symbol": symbol, "limit": limit},
            timeout=10.0,
        )
        if resp.status_code != 200:
            logger.warning(f"Funding rate {symbol} HTTP {resp.status_code}")
            return None
        raw = resp.json()
        if not raw:
            return None
        fr = pd.DataFrame(raw)
        fr["fundingTime"] = pd.to_datetime(fr["fundingTime"], unit="ms", utc=True)
        fr["fundingRate"] = fr["fundingRate"].astype(float)
        fr.set_index("fundingTime", inplace=True)
        return fr["fundingRate"]
    except Exception as e:
        logger.error(f"fetch_funding_rate {symbol} 失敗: {e}")
        return None


async def fetch_ohlcv(client: httpx.AsyncClient, symbol: str, interval: str = "1h", limit: int = 300) -> pd.DataFrame | None:
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = await client.get(BINANCE_KLINE_URL, params=params, timeout=10.0)
        if resp.status_code != 200:
            logger.warning(f"Binance kline {symbol} HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        raw = resp.json()
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.set_index("open_time", inplace=True)

        # 合併資金費率：8H 一筆，前向填補到每根 1H K 棒
        funding = await fetch_funding_rate(client, symbol)
        if funding is not None and len(funding) > 0:
            df["funding_rate"] = funding.reindex(df.index, method="ffill")
            df["funding_rate"] = df["funding_rate"].bfill().fillna(0.0)
        return df
    except Exception as e:
        logger.error(f"fetch_ohlcv {symbol} 失敗: {e}")
        return None


async def market_tick_loop(orchestrator, interval_seconds: int = 60):
    """每 interval_seconds 秒抓 Binance OHLCV → crypto tick() → 更新即時餘額。"""
    logger.info("📡 加密市場數據背景任務啟動")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                market_data: dict[str, pd.DataFrame] = {}
                for symbol in CRYPTO_SYMBOLS:
                    df = await fetch_ohlcv(client, symbol, TIMEFRAME, OHLCV_LIMIT)
                    if df is not None and len(df) >= 200:
                        market_data[symbol] = df

                if market_data:
                    context = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "timeframe": TIMEFRAME,
                    }
                    await orchestrator.crypto.tick(market_data, context)
                    # 順手更新即時 Binance 餘額（有設 key 才會動作）
                    try:
                        await orchestrator.crypto.router.fetch_binance_balance()
                    except Exception:
                        pass
                    logger.info(f"✅ 加密 tick 完成 總聊天={len(orchestrator.crypto.chat_messages)}")
                else:
                    logger.warning("⚠️ 加密本輪沒有可用市場數據，跳過 tick")
            except Exception as e:
                logger.error(f"market_tick_loop 錯誤: {e}", exc_info=True)

            await asyncio.sleep(interval_seconds)


# ── 美股池 ────────────────────────────────────────────────────────────────────

STOCK_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA"]


async def fetch_stock_ohlcv(symbol: str, period: str = "3mo", interval: str = "1h") -> pd.DataFrame | None:
    """用 yfinance 抓股票 OHLCV（在 executor 中執行，避免阻塞事件循環）"""
    try:
        import yfinance as yf
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: yf.download(symbol, period=period, interval=interval,
                                 progress=False, auto_adjust=True),
        )
        if df is None or len(df) < 10:
            return None
        df.columns = [c.lower() for c in df.columns]
        df.index.name = "open_time"
        return df
    except Exception as e:
        logger.error(f"fetch_stock_ohlcv {symbol} 失敗: {e}")
        return None


async def stock_tick_loop(orchestrator, interval_seconds: int = 300):
    """每 interval_seconds 秒用 yfinance 抓美股 OHLCV → stock tick()。"""
    logger.info("📡 美股市場數據背景任務啟動")
    while True:
        try:
            market_data: dict[str, pd.DataFrame] = {}
            for symbol in STOCK_SYMBOLS:
                df = await fetch_stock_ohlcv(symbol)
                if df is not None and len(df) >= 200:
                    market_data[symbol] = df

            if market_data:
                context = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "timeframe": "1H",
                }
                await orchestrator.stock.tick(market_data, context)
                logger.info(f"✅ 美股 tick 完成 總聊天={len(orchestrator.stock.chat_messages)}")
            else:
                logger.warning("⚠️ 美股本輪沒有可用數據，跳過 tick")
        except Exception as e:
            logger.error(f"stock_tick_loop 錯誤: {e}", exc_info=True)

        await asyncio.sleep(interval_seconds)
