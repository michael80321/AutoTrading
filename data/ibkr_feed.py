"""
IBKR Paper Trading Feed
⚠️  需要本機執行 TWS 或 IB Gateway(port 7497)
    Railway 雲端部署時自動 fallback 到 MockFeed

連接方式:
  本機開發: TWS Paper Trading 模式開啟後直接連
  雲端:     用 ngrok/tailscale 把 TWS port 7497 轉發到 Railway,
            然後設環境變數 IBKR_HOST / IBKR_PORT
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd

from AutoTrading.data.mock_feed import MockFeed

logger = logging.getLogger(__name__)


class IBKRFeed:
    """
    從 IBKR Paper Account 取得 OHLCV。
    若 ib_insync 不可用或 TWS 未啟動,自動切換 MockFeed。
    """

    def __init__(self, symbol: str, exchange: str = "SMART", currency: str = "USD"):
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency
        self._ib = None
        self._use_mock = True
        self._mock = MockFeed(symbol, initial_price=450.0, seed=hash(symbol) % 1000)

    def initialize(self) -> bool:
        host = os.getenv("IBKR_HOST", "127.0.0.1")
        port = int(os.getenv("IBKR_PORT", "7497"))
        client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))

        try:
            import ib_insync
            ib = ib_insync.IB()
            ib.connect(host, port, clientId=client_id, timeout=5)
            self._ib = ib
            self._use_mock = False
            logger.info(f"[IBKRFeed:{self.symbol}] ✅ TWS 連線成功 {host}:{port}")
            return True
        except ImportError:
            logger.warning("[IBKRFeed] ib_insync 未安裝,切換 MockFeed")
        except Exception as e:
            logger.warning(f"[IBKRFeed:{self.symbol}] TWS 連線失敗({e}),切換 MockFeed")
        self._use_mock = True
        return False

    def fetch(self) -> pd.DataFrame:
        if self._use_mock:
            return self._mock.next()
        try:
            from ib_insync import Stock
            contract = Stock(self.symbol, self.exchange, self.currency)
            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="1 D",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )
            df = pd.DataFrame(
                [(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars],
                columns=["ts", "open", "high", "low", "close", "volume"],
            ).set_index("ts")
            return df.iloc[-300:]
        except Exception as e:
            logger.error(f"[IBKRFeed:{self.symbol}] fetch 失敗: {e}")
            return self._mock.next()


def make_ibkr_feeds(symbols: list[str] | None = None) -> dict[str, IBKRFeed]:
    if symbols is None:
        symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
    feeds = {}
    for sym in symbols:
        feed = IBKRFeed(sym)
        feed.initialize()
        feeds[sym] = feed
    return feeds
