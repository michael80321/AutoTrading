"""
eval_layer.backtest — 回測引擎（工具最容易騙到自己的地方）。

每一條都不可省，缺一條結果就不可信：
1. 扣真實交易成本：每次部位變動扣單邊手續費。fee 不可為 0（為 0 直接報錯）。
2. 扣滑價：每次成交額外扣滑價緩衝。slip 不可為 0。
3. t+1 開盤成交：第 t 天收盤的訊號，在第 t+1 天『開盤價』成交。
   嚴禁用第 t 天訊號在第 t 天收盤成交（偷看未來）。
4. 強制對比 Buy & Hold（buy_and_hold）。

實作為逐日事件模擬（持有「資產單位數」vs「現金」），完全可稽核：
- 買入：buy_price = open*(1+slip)，units = cash*(1-fee)/buy_price。
- 賣出：cash = units*open*(1-slip)*(1-fee)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config


def _validate_costs(fee: float, slip: float) -> None:
    # 工具的良心：拒絕把成本設為 0
    if fee <= config.MIN_FEE_ONE_WAY:
        raise ValueError(
            f"手續費 fee={fee} 不可為 0（或趨近 0）。把成本歸零會讓回測說謊。"
            f"這是刻意的防呆，不是 bug。"
        )
    if slip <= config.MIN_SLIPPAGE:
        raise ValueError(
            f"滑價 slip={slip} 不可為 0（或趨近 0）。真實成交一定有滑價。"
            f"這是刻意的防呆，不是 bug。"
        )


def backtest(
    df: pd.DataFrame,
    signal: pd.Series,
    fee: float = config.FEE_ONE_WAY,
    slip: float = config.SLIPPAGE,
    initial: float = config.INITIAL_CAPITAL,
) -> dict:
    """逐日模擬。signal[t] 在 t+1 開盤成交。

    回傳 dict：
      equity      權益曲線 (pd.Series)
      returns     每日權益單利報酬 (pd.Series)
      position    每日實際持有部位 0/1 (pd.Series)
      trades      完成的回合交易清單 [{entry_date, exit_date, ret, open_at_end}]
      n_trades    進場次數
    """
    _validate_costs(fee, slip)
    if len(df) < 2:
        raise ValueError("backtest(): 資料至少需 2 根 K 棒")

    idx = df.index
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    sig = signal.reindex(idx).fillna(0).to_numpy(dtype=int)  # t 收盤決定的目標部位
    n = len(df)

    cash = float(initial)
    units = 0.0
    pos = 0
    equity = np.empty(n, dtype=float)
    positions = np.zeros(n, dtype=int)
    trades: list[dict] = []
    entry_equity: float | None = None
    entry_date = None

    for i in range(n):
        # 目標部位來自『昨日收盤』訊號，於『今日開盤』成交（t+1 成交，防 look-ahead）
        target = int(sig[i - 1]) if i >= 1 else 0
        if target != pos:
            price = opens[i]
            if target == 1:  # 買進
                buy_price = price * (1.0 + slip)
                entry_equity = cash  # 進場前權益（現金全押）
                units = (cash * (1.0 - fee)) / buy_price
                cash = 0.0
                pos = 1
                entry_date = idx[i]
            else:  # 賣出（出場）
                sell_price = price * (1.0 - slip)
                cash = units * sell_price * (1.0 - fee)
                trades.append({
                    "entry_date": entry_date,
                    "exit_date": idx[i],
                    "ret": cash / entry_equity - 1.0,  # 含進出兩段成本的回合淨報酬
                    "open_at_end": False,
                })
                units = 0.0
                pos = 0
        # 收盤 mark-to-market
        equity[i] = cash + units * closes[i]
        positions[i] = pos

    # 期末仍持倉 → 以期末收盤標記為一筆（記帳用，不扣出場成本，因為尚未真的賣出）
    if pos == 1 and entry_equity is not None:
        trades.append({
            "entry_date": entry_date,
            "exit_date": idx[-1],
            "ret": equity[-1] / entry_equity - 1.0,
            "open_at_end": True,
        })

    eq = pd.Series(equity, index=idx, name="equity")
    returns = eq.pct_change().fillna(0.0)
    returns.name = "returns"
    pos_series = pd.Series(positions, index=idx, name="position")
    n_entries = sum(1 for t in trades if not t["open_at_end"]) + (1 if pos == 1 else 0)

    return {
        "equity": eq,
        "returns": returns,
        "position": pos_series,
        "trades": trades,
        "n_trades": n_entries,
    }


def buy_and_hold(
    df: pd.DataFrame,
    fee: float = config.FEE_ONE_WAY,
    slip: float = config.SLIPPAGE,
    initial: float = config.INITIAL_CAPITAL,
) -> dict:
    """基準線：同標的、同期間、同起始資金。

    於『第一個可成交 K 棒（i=1）的開盤』進場，扣一次手續費+滑價後抱到底。
    與策略在每個分段內的起跑點對齊，確保公平比較。
    """
    _validate_costs(fee, slip)
    if len(df) < 2:
        raise ValueError("buy_and_hold(): 資料至少需 2 根 K 棒")

    idx = df.index
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    n = len(df)

    buy_price = opens[1] * (1.0 + slip)
    units = (initial * (1.0 - fee)) / buy_price

    equity = np.empty(n, dtype=float)
    equity[0] = initial
    for i in range(1, n):
        equity[i] = units * closes[i]

    eq = pd.Series(equity, index=idx, name="equity")
    returns = eq.pct_change().fillna(0.0)
    returns.name = "returns"
    return {
        "equity": eq,
        "returns": returns,
        "position": pd.Series(1, index=idx, name="position"),
        "trades": [{"entry_date": idx[1], "exit_date": idx[-1],
                    "ret": eq.iloc[-1] / initial - 1.0, "open_at_end": True}],
        "n_trades": 1,
    }
