"""
合成資料 Feed — 無外部依賴,適合 Railway 冷啟動與測試
每次 tick 在現有資料後面追加一根合成 K 棒,模擬即時 feed
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta


class MockFeed:
    """
    為一個 symbol 維護滾動 OHLCV buffer,每次 next() 追加一根 K 棒。
    可配置 onchain / orderflow / funding 欄位以觸發對應策略。
    """

    def __init__(
        self,
        symbol: str,
        initial_price: float = 50_000.0,
        n_warmup: int = 300,
        seed: int = 42,
        extra_cols: list[str] | None = None,
    ):
        self.symbol = symbol
        self.price = initial_price
        self.rng = np.random.default_rng(seed)
        self.extra_cols = extra_cols or []
        self._buf = self._make_warmup(n_warmup)

    # ─── 內部 ──────────────────────────────────────────

    def _make_warmup(self, n: int) -> pd.DataFrame:
        rng = self.rng
        vol = self.price * 0.005
        changes = rng.normal(0, vol, n)
        closes = np.cumsum(changes) + self.price
        closes = np.maximum(closes, self.price * 0.01)
        spread = np.abs(rng.normal(0, vol * 0.4, n))
        opens = closes + rng.normal(0, vol * 0.2, n)
        highs = np.maximum(closes, opens) + spread
        lows = np.maximum(np.minimum(closes, opens) - spread, closes * 0.001)
        volumes = rng.exponential(1_000.0, n) + 100.0
        end = datetime(2024, 1, 1)
        index = pd.date_range(end=end, periods=n, freq="1min")

        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows,
             "close": closes, "volume": volumes},
            index=index,
        )
        self.price = float(closes[-1])
        self._add_extra(df)
        return df

    def _add_extra(self, df: pd.DataFrame):
        n = len(df)
        rng = self.rng
        if "buy_volume" in self.extra_cols:
            r = rng.uniform(0.3, 0.7, n)
            df["buy_volume"] = df["volume"] * r
            df["sell_volume"] = df["volume"] * (1 - r)
        if "funding_rate" in self.extra_cols:
            df["funding_rate"] = rng.normal(0.0001, 0.0002, n)
        if "exchange_inflow" in self.extra_cols:
            df["exchange_inflow"] = rng.exponential(500, n)
            df["exchange_outflow"] = rng.exponential(600, n)
            df["whale_tx_count"] = rng.poisson(10, n)

    def _next_bar(self) -> pd.Series:
        vol = self.price * 0.005
        chg = self.rng.normal(0, vol)
        close = max(self.price * 0.01, self.price + chg)
        spread = abs(self.rng.normal(0, vol * 0.4))
        open_ = close + self.rng.normal(0, vol * 0.2)
        high = max(close, open_) + spread
        low = max(max(close, open_) * 0.001, min(close, open_) - spread)
        vol_val = self.rng.exponential(1_000.0) + 100.0
        self.price = close
        ts = self._buf.index[-1] + timedelta(minutes=1)

        row = {"open": open_, "high": high, "low": low,
               "close": close, "volume": vol_val}
        if "buy_volume" in self.extra_cols:
            r = self.rng.uniform(0.3, 0.7)
            row["buy_volume"] = vol_val * r
            row["sell_volume"] = vol_val * (1 - r)
        if "funding_rate" in self.extra_cols:
            row["funding_rate"] = self.rng.normal(0.0001, 0.0002)
        if "exchange_inflow" in self.extra_cols:
            row["exchange_inflow"] = self.rng.exponential(500)
            row["exchange_outflow"] = self.rng.exponential(600)
            row["whale_tx_count"] = self.rng.poisson(10)
        return pd.Series(row, name=ts)

    # ─── 公開 API ──────────────────────────────────────

    def next(self) -> pd.DataFrame:
        """追加一根 K 棒並回傳最新 buffer(最近 300 根)"""
        new_bar = self._next_bar()
        new_row = pd.DataFrame([new_bar])
        new_row.index = [new_bar.name]
        self._buf = pd.concat([self._buf, new_row]).iloc[-300:]
        return self._buf.copy()


# ─── 一次建立兩池所需的所有 feeds ─────────────────────────

def make_crypto_feeds() -> dict[str, MockFeed]:
    return {
        "BTCUSDT": MockFeed("BTCUSDT", 50_000.0, extra_cols=["buy_volume", "funding_rate", "exchange_inflow"], seed=1),
        "ETHUSDT": MockFeed("ETHUSDT", 3_000.0,  extra_cols=["buy_volume", "funding_rate"], seed=2),
        "SOLUSDT": MockFeed("SOLUSDT", 150.0,    extra_cols=["buy_volume"], seed=3),
    }


def make_stock_feeds() -> dict[str, MockFeed]:
    return {
        "SPY":  MockFeed("SPY",  450.0, seed=10),
        "QQQ":  MockFeed("QQQ",  380.0, seed=11),
        "AAPL": MockFeed("AAPL", 180.0, seed=12),
    }
