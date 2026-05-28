"""
Binance Testnet 即時 K 棒 Feed
- 使用 ccxt REST API 輪詢(最穩定,testnet 支援良好)
- 每 60 秒取一次最新 300 根 1m K 棒,更新 buffer
- 若 testnet 不可用,自動 fallback 到 MockFeed
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

from AutoTrading.data.mock_feed import MockFeed

try:
    import ccxt as _ccxt
except ImportError:
    _ccxt = None  # type: ignore

logger = logging.getLogger(__name__)


class BinanceFeed:
    """
    從 Binance Testnet 取得 OHLCV 資料。
    credentials 透過環境變數注入:
      BINANCE_TESTNET_API_KEY
      BINANCE_TESTNET_SECRET
    """

    TESTNET_URL = "https://testnet.binance.vision/api"

    def __init__(self, symbol: str, timeframe: str = "1m", limit: int = 300):
        self.symbol = symbol          # e.g. "BTC/USDT"
        self.ccxt_symbol = symbol     # ccxt format
        self.timeframe = timeframe
        self.limit = limit
        self._exchange = None
        self._mock_fallback = MockFeed(
            symbol.replace("/", ""),
            initial_price=50_000.0 if "BTC" in symbol else 3_000.0,
            extra_cols=["buy_volume", "funding_rate"],
        )
        self._use_mock = False
        self._buf: Optional[pd.DataFrame] = None

    def initialize(self) -> bool:
        """嘗試連接 Binance testnet,失敗則切換 mock"""
        api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        secret = os.getenv("BINANCE_TESTNET_SECRET", "")

        if not api_key or not secret:
            logger.warning(f"[BinanceFeed:{self.symbol}] 無 API 金鑰,切換 MockFeed")
            self._use_mock = True
            return False

        if _ccxt is None:
            logger.warning(f"[BinanceFeed:{self.symbol}] ccxt 未安裝,切換 MockFeed")
            self._use_mock = True
            return False

        try:
            self._exchange = _ccxt.binance({
                "apiKey": api_key,
                "secret": secret,
                "options": {"defaultType": "spot"},
                "urls": {"api": {"public": self.TESTNET_URL}},
            })
            self._exchange.load_markets()
            logger.info(f"[BinanceFeed:{self.symbol}] ✅ Testnet 連線成功")
            return True
        except Exception as e:
            logger.warning(f"[BinanceFeed:{self.symbol}] testnet 連線失敗({e}),切換 MockFeed")
            self._use_mock = True
            return False

    def fetch(self) -> pd.DataFrame:
        """取得最新 OHLCV DataFrame,失敗時用 mock"""
        if self._use_mock:
            return self._mock_fallback.next()
        try:
            raw = self._exchange.fetch_ohlcv(
                self.ccxt_symbol, self.timeframe, limit=self.limit
            )
            df = pd.DataFrame(
                raw, columns=["ts", "open", "high", "low", "close", "volume"]
            )
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            df = df.set_index("ts")
            self._buf = df
            return df
        except Exception as e:
            logger.error(f"[BinanceFeed:{self.symbol}] fetch 失敗: {e}")
            return self._mock_fallback.next()


def make_binance_feeds(symbols: list[str] | None = None) -> dict[str, BinanceFeed]:
    """建立加密池所有 symbol 的 feed"""
    if symbols is None:
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    feeds = {}
    for sym in symbols:
        feed = BinanceFeed(sym)
        feed.initialize()
        feeds[sym.replace("/", "")] = feed   # key = "BTCUSDT"
    return feeds
