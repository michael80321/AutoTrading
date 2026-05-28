"""
Binance WebSocket K 棒資料 feed
- 訂閱多個交易對的 K 棒流 (kline stream)
- 組裝成 pd.DataFrame 並回呼 on_candle
- 連線中斷自動重連 (exponential backoff)
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream?streams="


class BinanceFeed:
    """
    訂閱 Binance 多幣對 K 棒 WebSocket 流
    用法:
        feed = BinanceFeed(["BTCUSDT", "ETHUSDT"], "15m", on_candle=handler)
        await feed.start()
    """

    def __init__(
        self,
        symbols: list[str],
        interval: str = "15m",
        on_candle: Optional[Callable] = None,
    ):
        self.symbols = [s.lower() for s in symbols]
        self.interval = interval
        self.on_candle = on_candle
        self._running = False
        # 記憶每個 symbol 的歷史 K 棒 (最多 500 根)
        self._history: dict[str, list[dict]] = {s: [] for s in symbols}

    def _build_url(self) -> str:
        streams = "/".join(f"{s}@kline_{self.interval}" for s in self.symbols)
        return BINANCE_WS_BASE + streams

    def _parse_kline(self, msg: dict) -> Optional[tuple[str, dict]]:
        data = msg.get("data", {})
        if data.get("e") != "kline":
            return None
        k = data["k"]
        symbol = k["s"]
        candle = {
            "timestamp": datetime.fromtimestamp(k["t"] / 1000),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
            "closed": k["x"],  # True = K 棒已收盤
        }
        return symbol, candle

    def get_dataframe(self, symbol: str) -> pd.DataFrame:
        rows = self._history.get(symbol.upper(), [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df

    async def _process_message(self, raw: str):
        try:
            msg = json.loads(raw)
            result = self._parse_kline(msg)
            if not result:
                return
            symbol, candle = result
            hist = self._history.setdefault(symbol, [])
            if candle["closed"]:
                hist.append(candle)
                if len(hist) > 500:
                    self._history[symbol] = hist[-500:]
            if self.on_candle:
                df = self.get_dataframe(symbol)
                await self.on_candle(symbol, candle, df)
        except Exception as e:
            logger.error(f"BinanceFeed message 處理錯誤: {e}")

    async def start(self):
        if not WS_AVAILABLE:
            logger.error("websockets 套件未安裝,BinanceFeed 無法啟動")
            return
        self._running = True
        url = self._build_url()
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info(f"✅ Binance WS 已連線: {len(self.symbols)} 個交易對")
                    backoff = 1
                    async for message in ws:
                        if not self._running:
                            break
                        await self._process_message(message)
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"Binance WS 斷線 ({e}),{backoff}s 後重連")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def stop(self):
        self._running = False
