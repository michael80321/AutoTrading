"""
美股市場資料 feed — Polygon.io REST + WebSocket
- 即時 K 棒 (分鐘 / 日線)
- SPDR 板塊 ETF 報價 (Rotation Sage 用)
- 期權鏈快照 (Gamma Tide 用)
- 財報日曆 (Earnings Hawk 用)
需要環境變數 POLYGON_API_KEY
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

POLYGON_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_REST = "https://api.polygon.io"

SPDR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLB", "XLP", "XLRE", "XLU", "XLC"]

try:
    import httpx
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False


class StockFeed:
    """
    美股資料 feed (Polygon.io)
    """

    def __init__(self, symbols: list[str], on_candle: Optional[Callable] = None):
        self.symbols = symbols
        self.on_candle = on_candle
        self._history: dict[str, list[dict]] = {}
        self._earnings_cache: dict[str, datetime] = {}
        self._sector_cache: dict[str, float] = {}

    async def _get(self, path: str, params: dict = None) -> Optional[dict]:
        if not HTTP_AVAILABLE or not POLYGON_KEY:
            logger.warning("httpx 或 POLYGON_API_KEY 未設定,跳過 API 請求")
            return None
        params = params or {}
        params["apiKey"] = POLYGON_KEY
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{POLYGON_REST}{path}", params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Polygon API 錯誤 {path}: {e}")
            return None

    async def fetch_daily_bars(self, symbol: str, days: int = 365) -> pd.DataFrame:
        """取得日線 OHLCV"""
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = await self._get(
            f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}",
            {"adjusted": "true", "sort": "asc", "limit": days},
        )
        if not data or not data.get("results"):
            return pd.DataFrame()
        rows = [
            {
                "timestamp": datetime.fromtimestamp(r["t"] / 1000),
                "open": r["o"], "high": r["h"], "low": r["l"],
                "close": r["c"], "volume": r["v"],
            }
            for r in data["results"]
        ]
        df = pd.DataFrame(rows).set_index("timestamp")
        self._history[symbol] = rows
        return df

    async def fetch_earnings_calendar(self, symbols: list[str]) -> dict[str, datetime]:
        """財報日曆 — 每個 symbol 的下一個財報日"""
        result = {}
        for symbol in symbols:
            data = await self._get(
                f"/vX/reference/financials",
                {"ticker": symbol, "limit": 1, "sort": "period_of_report_date", "order": "desc"},
            )
            if data and data.get("results"):
                r = data["results"][0]
                report_date = r.get("filing_date", "")
                if report_date:
                    try:
                        result[symbol] = datetime.strptime(report_date, "%Y-%m-%d")
                    except ValueError:
                        pass
        self._earnings_cache.update(result)
        return result

    async def fetch_sector_prices(self) -> dict[str, float]:
        """SPDR 板塊 ETF 收盤價 — Rotation Sage 用"""
        prices = {}
        for etf in SPDR_ETFS:
            data = await self._get(f"/v2/last/trade/{etf}")
            if data and data.get("results"):
                prices[etf] = data["results"].get("p", 0.0)
        self._sector_cache.update(prices)
        return prices

    async def fetch_option_chain(self, symbol: str, expiry_days: int = 30) -> list[dict]:
        """期權鏈快照 — Gamma Tide 用"""
        exp_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d")
        data = await self._get(
            "/v3/reference/options/contracts",
            {"underlying_ticker": symbol, "expiration_date.lte": exp_date, "limit": 250},
        )
        if not data or not data.get("results"):
            return []
        return data["results"]

    async def poll_loop(self, interval_seconds: int = 60):
        """定時拉取所有股票日線資料"""
        while True:
            for symbol in self.symbols:
                df = await self.fetch_daily_bars(symbol, days=60)
                if not df.empty and self.on_candle:
                    candle = {
                        "timestamp": df.index[-1],
                        "close": df["close"].iloc[-1],
                        "closed": True,
                    }
                    await self.on_candle(symbol, candle, df)
            await asyncio.sleep(interval_seconds)

    def get_dataframe(self, symbol: str) -> pd.DataFrame:
        rows = self._history.get(symbol, [])
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("timestamp")

    def get_sector_context(self) -> dict:
        return {"sector_prices": self._sector_cache}

    def get_earnings_context(self) -> dict:
        return {"earnings_calendar": self._earnings_cache}
