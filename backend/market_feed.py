"""
市場數據背景餵送 — 每分鐘從 Binance 抓 OHLCV，驅動 18 席分析師 tick
無 API key 時使用公開 REST endpoint（K 線不需授權）
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

# 加密池監控的標的（各學派都有用到的 symbol）
CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
OHLCV_LIMIT = 300  # 每次抓 300 根 K 線，供策略計算指標用
TIMEFRAME = "1h"

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"


async def fetch_ohlcv(client: httpx.AsyncClient, symbol: str, interval: str = "1h", limit: int = 300) -> pd.DataFrame | None:
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = await client.get(BINANCE_KLINE_URL, params=params, timeout=10.0)
        if resp.status_code != 200:
            logger.warning(f"Binance kline {symbol} HTTP {resp.status_code}")
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
