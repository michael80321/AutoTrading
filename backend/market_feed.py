"""
市場數據背景餵送
- 加密池：每 60 秒從 Bybit 公開 API 抓 OHLCV（Binance 在 Railway US 被封鎖）
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
TIMEFRAME = "1h"

# Bybit 公開 K 線 API（不需授權，不封鎖美國 IP）
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"


async def fetch_ohlcv(client: httpx.AsyncClient, symbol: str, interval: str = "60", limit: int = 300) -> pd.DataFrame | None:
    """從 Bybit 抓 OHLCV。interval 單位為分鐘（60=1H）。"""
    try:
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        resp = await client.get(BYBIT_KLINE_URL, params=params, timeout=10.0)
        if resp.status_code != 200:
            logger.warning(f"Bybit kline {symbol} HTTP {resp.status_code}")
            return None
        body = resp.json()
        if body.get("retCode") != 0:
            logger.warning(f"Bybit kline {symbol} error: {body.get('retMsg')}")
            return None
        # Bybit 回傳最新在前，需反轉；欄位: [startTime, open, high, low, close, volume, turnover]
        rows = body["result"]["list"][::-1]
        df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"].astype(float), unit="ms", utc=True)
        df.set_index("open_time", inplace=True)
        return df
    except Exception as e:
        logger.error(f"fetch_ohlcv {symbol} 失敗: {e}")
        return None


async def market_tick_loop(orchestrator, redis_bus, interval_seconds: int = 60):
    """
    每 interval_seconds 秒：
    1. 從 Binance 公開 API 抓最新 OHLCV（不需要 API Key）
    2. 呼叫 crypto pool tick()，讓 18 席分析師產生訊號 + 聊天
    3. 將新產生的聊天訊息推送到 Redis → WebSocket
    """
    logger.info("📡 市場數據背景任務啟動")
    last_chat_len = 0
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

                    # 推送新訊息到 Redis → WebSocket
                    new_msgs = orchestrator.crypto.chat_messages[last_chat_len:]
                    for msg in new_msgs:
                        await redis_bus.publish("crypto", msg)
                    last_chat_len = len(orchestrator.crypto.chat_messages)

                    logger.info(f"✅ tick 完成 新訊息={len(new_msgs)} 總聊天={last_chat_len}")
                else:
                    logger.warning("⚠️ 本輪沒有可用市場數據，跳過 tick")
            except Exception as e:
                logger.error(f"market_tick_loop 錯誤: {e}")

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


async def stock_tick_loop(orchestrator, redis_bus, interval_seconds: int = 300):
    """
    每 interval_seconds 秒：
    1. 用 yfinance 抓美股 OHLCV
    2. 呼叫 stock pool tick()，讓 18 席美股分析師產生訊號 + 聊天
    3. 推送新訊息到 Redis → WebSocket
    """
    logger.info("📡 美股市場數據背景任務啟動")
    last_chat_len = 0
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

                new_msgs = orchestrator.stock.chat_messages[last_chat_len:]
                for msg in new_msgs:
                    await redis_bus.publish("stock", msg)
                last_chat_len = len(orchestrator.stock.chat_messages)

                logger.info(f"✅ 美股 tick 完成 新訊息={len(new_msgs)} 總聊天={last_chat_len}")
            else:
                logger.warning("⚠️ 美股本輪沒有可用數據，跳過 tick")
        except Exception as e:
            logger.error(f"stock_tick_loop 錯誤: {e}")

        await asyncio.sleep(interval_seconds)
