"""
eval_layer.metrics — 指標計算。主角不是勝率。

決策用（主畫面）：扣成本後總報酬、最大回撤、夏普值、交易次數/換手、CAGR。
僅供參考（角落，明確標註不可作為決策依據）：勝率、平均盈虧比。

報酬口徑：統一單利（simple returns），與 config.RETURN_CONVENTION 一致。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config

# 每個指標的白話解讀，report 會一併輸出，避免只看數字不看意義。
METRIC_GLOSSARY = {
    "total_return": "扣成本後總報酬：這段期間你的本金總共變成幾倍（含所有手續費與滑價）。",
    "cagr": "年化報酬 (CAGR)：把總報酬換算成『平均每年』成長率，方便跨期間比較。",
    "max_drawdown": "最大回撤：從最高點往下虧最多的幅度。代表你心理上要撐得住多痛。",
    "sharpe": "夏普值（年化）：每承受一單位波動風險換到多少報酬。>1 還行，<0 代表賠錢還很顛。",
    "n_trades": "交易次數：進場幾次。次數越多，成本侵蝕越兇，也越可能在交易雜訊。",
    "trades_per_year": "年均交易次數：換手頻率。動量策略本該低頻，過高要警覺。",
    "win_rate": "[僅供參考] 勝率：賺錢回合佔比。高勝率≠賺錢，不可作為決策依據。",
    "avg_win_loss": "[僅供參考] 平均盈虧比：平均每筆賺的 ÷ 平均每筆賠的。",
}

# 主畫面決策指標 vs 角落僅供參考指標
DECISION_METRICS = ["total_return", "cagr", "max_drawdown", "sharpe", "n_trades", "trades_per_year"]
REFERENCE_METRICS = ["win_rate", "avg_win_loss"]


def _max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    return float(abs(dd.min()))


def _sharpe(returns: pd.Series, periods_per_year: int) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * r.mean() / r.std())


def _cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    start_val, end_val = float(equity.iloc[0]), float(equity.iloc[-1])
    if start_val <= 0 or end_val <= 0:
        return 0.0
    if isinstance(equity.index, pd.DatetimeIndex):
        days = (equity.index[-1] - equity.index[0]).days
        years = days / 365.25 if days > 0 else 0
    else:
        years = len(equity) / config.PERIODS_PER_YEAR
    if years <= 0:
        return 0.0
    return float((end_val / start_val) ** (1.0 / years) - 1.0)


def metrics(result: dict, periods_per_year: int = config.PERIODS_PER_YEAR) -> dict:
    """從 backtest()/buy_and_hold() 的回傳算出第 6 節全部指標。"""
    equity: pd.Series = result["equity"]
    returns: pd.Series = result["returns"]
    trades: list[dict] = result.get("trades", [])

    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)

    # 回合勝率與盈虧比（角落參考）
    trade_rets = [t["ret"] for t in trades]
    wins = [r for r in trade_rets if r > 0]
    losses = [r for r in trade_rets if r <= 0]
    win_rate = (len(wins) / len(trade_rets)) if trade_rets else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 0.0
    avg_win_loss = float(avg_win / avg_loss) if avg_loss > 0 else (float("inf") if avg_win > 0 else 0.0)

    # 年均交易次數
    if isinstance(equity.index, pd.DatetimeIndex):
        days = (equity.index[-1] - equity.index[0]).days
        years = days / 365.25 if days > 0 else (len(equity) / periods_per_year)
    else:
        years = len(equity) / periods_per_year
    n_trades = result.get("n_trades", len([t for t in trades if not t.get("open_at_end")]))
    trades_per_year = float(n_trades / years) if years > 0 else 0.0

    return {
        "total_return": total_return,
        "cagr": _cagr(equity),
        "max_drawdown": _max_drawdown(equity),
        "sharpe": _sharpe(returns, periods_per_year),
        "n_trades": int(n_trades),
        "trades_per_year": round(trades_per_year, 2),
        "win_rate": round(win_rate, 4),
        "avg_win_loss": round(avg_win_loss, 4) if np.isfinite(avg_win_loss) else avg_win_loss,
    }
