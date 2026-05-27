"""
合成資料產生器 — 供 pytest fixtures 使用。
所有函式純 Python/numpy/pandas,無外部 API 依賴。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime


# ─────────────────────────────────────────────
# 基礎 OHLCV 產生器
# ─────────────────────────────────────────────

def make_ohlcv(
    n_bars: int = 300,
    start_price: float = 50_000.0,
    freq: str = "1h",
    seed: int = 42,
    trend: str = "flat",
    add_orderflow: bool = False,
    add_onchain: bool = False,
    add_funding: bool = False,
    add_mempool: bool = False,
) -> pd.DataFrame:
    """
    生成合成 OHLCV DataFrame，index 為 DatetimeIndex。

    trend 選項:
      "flat"            — 平緩盤整隨機遊走
      "up"              — 整體上漲,觸發 BOS / 突破類策略
      "down"            — 整體下跌
      "mean_rev_long"   — 最後 20 根急跌,z-score 極低 → 觸發均值回歸做多
      "mean_rev_short"  — 最後 20 根急漲,z-score 極高 → 觸發均值回歸做空
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-01-01", periods=n_bars, freq=freq)

    vol_per_bar = start_price * 0.005
    changes = rng.normal(0, vol_per_bar, n_bars)

    if trend == "up":
        changes += start_price * 0.0008
    elif trend == "down":
        changes -= start_price * 0.0008
    elif trend == "mean_rev_long":
        changes[-20:] -= start_price * 0.003
    elif trend == "mean_rev_short":
        changes[-20:] += start_price * 0.003

    closes = np.cumsum(changes) + start_price
    closes = np.maximum(closes, start_price * 0.05)

    spread = np.abs(rng.normal(0, vol_per_bar * 0.4, n_bars))
    opens = closes + rng.normal(0, vol_per_bar * 0.2, n_bars)
    highs = np.maximum(closes, opens) + spread
    lows = np.minimum(closes, opens) - spread
    lows = np.maximum(lows, closes * 0.01)
    volumes = rng.exponential(scale=1_000.0, size=n_bars) + 100.0

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )

    if add_orderflow:
        ratio = rng.uniform(0.3, 0.7, n_bars)
        df["buy_volume"] = df["volume"] * ratio
        df["sell_volume"] = df["volume"] * (1 - ratio)

    if add_onchain:
        df["exchange_inflow"] = rng.exponential(500, n_bars)
        df["exchange_outflow"] = rng.exponential(700, n_bars)  # 淨流出 → 看漲
        df["whale_tx_count"] = rng.poisson(12, n_bars)
        df["stablecoin_inflow"] = rng.exponential(200, n_bars)

    if add_funding:
        df["funding_rate"] = rng.normal(0.0001, 0.0003, n_bars)

    if add_mempool:
        df["gas_price_gwei"] = rng.exponential(50, n_bars)
        df["mev_bundle_count"] = rng.poisson(30, n_bars)

    return df


# ─────────────────────────────────────────────
# 特製資料:確保特定策略觸發
# ─────────────────────────────────────────────

def make_mean_rev_long(n_bars: int = 300, seed: int = 42) -> pd.DataFrame:
    """
    最後一根 z-score < -2.5,確保 BayesMeanRev / BayesEQ 觸發 LONG。
    止損距離 = std * 1.5 / price ≈ 0.0035 > 0.003 門檻。
    動能 < 0.03 過濾也通過。
    """
    rng = np.random.default_rng(seed)
    base = 50_000.0
    index = pd.date_range("2023-01-01", periods=n_bars, freq="1h")

    closes = rng.normal(base, base * 0.002, n_bars)

    # 強制最後一根讓 rolling z-score < -2.2
    # rolling 窗口含最後一根本身,所以需要設更極端的值
    # 用 -4.5x 確保含入後 z 仍低於 -2.2
    bb = 20
    mu = closes[-bb - 1: -1].mean()
    sigma = closes[-bb - 1: -1].std()
    closes[-1] = mu - 4.5 * sigma

    spread = np.abs(rng.normal(0, base * 0.001, n_bars))
    opens = closes + rng.normal(0, base * 0.0008, n_bars)
    highs = np.maximum(closes, opens) + spread
    lows = np.minimum(closes, opens) - spread
    lows = np.maximum(lows, closes * 0.01)
    volumes = rng.exponential(1_000.0, n_bars) + 100.0

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


def make_bos_up(n_bars: int = 300, seed: int = 7) -> pd.DataFrame:
    """
    上升 BOS:前期高點被突破且 EMA 向上,觸發 SMCBeta LONG。
    """
    rng = np.random.default_rng(seed)
    base = 30_000.0
    index = pd.date_range("2023-01-01", periods=n_bars, freq="4h")

    # 整體上漲斜率
    drift = base * 0.0012
    changes = rng.normal(drift, base * 0.004, n_bars)
    closes = np.cumsum(changes) + base
    closes = np.maximum(closes, base * 0.1)

    spread = np.abs(rng.normal(0, base * 0.003, n_bars))
    opens = closes + rng.normal(0, base * 0.002, n_bars)
    highs = np.maximum(closes, opens) + spread
    lows = np.minimum(closes, opens) - spread
    lows = np.maximum(lows, closes * 0.01)
    volumes = rng.exponential(1_000.0, n_bars) + 100.0

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


def make_breakout_high(n_bars: int = 300, start_price: float = 450.0, seed: int = 42) -> pd.DataFrame:
    """
    最後一根 close 明確突破前 25 根的最高 high,觸發輪動/突破類策略。
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-01-01", periods=n_bars, freq="1D")
    closes = rng.normal(start_price, start_price * 0.01, n_bars)
    # 最後一根強制為前 30 根最高 high 的 1.02 倍
    prev_max = closes[-30:-1].max()
    closes[-1] = prev_max * 1.02
    spread = np.abs(rng.normal(0, start_price * 0.005, n_bars))
    opens = closes + rng.normal(0, start_price * 0.003, n_bars)
    highs = np.maximum(closes, opens) + spread
    lows = np.minimum(closes, opens) - spread
    lows = np.maximum(lows, closes * 0.01)
    volumes = rng.exponential(1_000.0, n_bars) + 100.0
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


def make_funding_extreme(n_bars: int = 60, rate: float = 0.0008, seed: int = 1) -> pd.DataFrame:
    """
    最後一根 funding_rate 極端正,觸發 ArbiterFunding SHORT。
    """
    rng = np.random.default_rng(seed)
    base = 50_000.0
    index = pd.date_range("2023-01-01", periods=n_bars, freq="8h")
    closes = rng.normal(base, base * 0.002, n_bars)
    spread = np.abs(rng.normal(0, base * 0.001, n_bars))
    opens = closes + rng.normal(0, base * 0.0005, n_bars)
    highs = np.maximum(closes, opens) + spread
    lows = np.minimum(closes, opens) - spread
    lows = np.maximum(lows, closes * 0.01)
    volumes = rng.exponential(500.0, n_bars) + 50.0

    fr = rng.normal(0.0001, 0.00005, n_bars)
    fr[-1] = rate  # 極端正費率
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": volumes, "funding_rate": fr},
        index=index,
    )
    return df


# ─────────────────────────────────────────────
# Context dict 工廠
# ─────────────────────────────────────────────

def ctx_risk_on(symbol: str = "BTCUSDT") -> dict:
    """Risk-on macro context,觸發 MacroHawk LONG"""
    return {
        "symbol": symbol,
        "macro_data": {
            "dxy_change_5d": -0.015,
            "us10y_bps_change_5d": 5,
            "vix": 15,
        },
    }


def ctx_risk_off(symbol: str = "BTCUSDT") -> dict:
    """Risk-off macro context,觸發 MacroHawk SHORT"""
    return {
        "symbol": symbol,
        "macro_data": {
            "dxy_change_5d": 0.025,
            "us10y_bps_change_5d": 22,
            "vix": 30,
        },
    }


def ctx_sentiment_long(symbol: str = "BTCUSDT") -> dict:
    """中等偏多情緒,觸發 PulseSentiment LONG"""
    return {
        "symbol": symbol,
        "sentiment_score": 0.75,
        "social_volume_zscore": 2.2,
    }


def ctx_triangular(profit_pct: float = 0.003) -> dict:
    """三角套利報價,觸發 TriadCrossEx LONG"""
    btc = 50_000.0
    eth_btc = 0.06
    # 刻意讓 path_a > 1 + profit_pct + fee(0.0012)
    eth_usdt = btc * eth_btc * (1 + profit_pct + 0.002)
    return {
        "symbol": "BTCUSDT",
        "triangular_quotes": {
            "BTCUSDT": btc,
            "ETHUSDT": eth_usdt,
            "ETHBTC": eth_btc,
        },
    }


def ctx_earnings(symbol: str = "AAPL", days_since: int = 2,
                 surprise: float = 0.08) -> dict:
    """
    財報後正向意外,觸發 EarningsHawk PEAD LONG。
    next_earnings 設在 30 天後,避免進入 pre-earnings 路徑。
    """
    from datetime import timedelta
    next_earnings = datetime(2024, 2, 1)  # 固定未來日期,避免進入 pre-earnings 路徑
    return {
        "symbol": symbol,
        "earnings_calendar": {symbol: next_earnings},
        "iv_rank": 30,
        "earnings_surprise_pct": surprise,
        "days_since_earnings": days_since,
    }


def ctx_sector_rotation(symbol: str = "XLK") -> dict:
    """
    板塊輪動 context,提供 sector_rs_ranks_history (6 天歷史排名)。
    XLK 排名從 8 → 1 (持續上升),觸發 RotationSage LONG。
    """
    sectors = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB", "XLRE", "XLC"]
    # 6 天歷史:XLK 排名從 8 持續升到 1
    history = []
    for day in range(6):
        rank_dict = {s: (i + 1) for i, s in enumerate(sectors)}  # base ranks
        # XLK 每天排名上升
        xlk_rank = 8 - day  # 8, 7, 6, 5, 4, 3
        rank_dict["XLK"] = xlk_rank
        history.append(rank_dict)
    return {
        "symbol": symbol,
        "sector_rs_ranks_history": history,
    }


# ─────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────

def seed_trade_log(
    bot,
    n_wins: int = 8,
    n_losses: int = 3,
    win_pnl: float = 15.0,
    loss_pnl: float = -8.0,
) -> None:
    """
    預填 bot.trade_log,使 compute_metrics().win_rate > 0.58。
    用於讓共識引擎的勝率過濾通過。
    """
    eq = bot.capital
    for _ in range(n_wins):
        bot.trade_log.append({"pnl": win_pnl, "side": "LONG"})
        eq += win_pnl
        bot.equity_curve.append(eq)
    for _ in range(n_losses):
        bot.trade_log.append({"pnl": loss_pnl, "side": "LONG"})
        eq += loss_pnl
        bot.equity_curve.append(eq)
