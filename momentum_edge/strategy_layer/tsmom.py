"""
strategy_layer — 時間序列動量 (Time-Series Momentum, TSMOM)。

規則刻意簡單，目的是檢驗『訊號本身』有沒有 edge，而不是部位管理技巧：
- 第 t 天收盤，計算過去 N 天累積報酬 = close[t] / close[t-N] - 1。
- > 0  → 目標部位 = 1（滿倉做多）。
- ≤ 0  → 目標部位 = 0（空手持現金）。
- 不做空、不開槓桿、不調整部位大小。

關鍵約束：訊號只用第 t 天收盤(含)之前的資料 → 禁止未來函數。
成交時點（t+1 開盤）由 eval_layer 處理，本模組只負責「在 t 收盤時你會想要什麼部位」。
"""
from __future__ import annotations

import pandas as pd


def tsmom_signal(df: pd.DataFrame, N: int = 90) -> pd.Series:
    """回傳每日目標部位 Series（0 或 1），index 對齊 df。

    signal[t] = 1 若 close[t]/close[t-N] - 1 > 0，否則 0。
    前 N 天無法計算 → 一律 0（空手），這是誠實的代價：動量策略需要 N 天暖身。
    """
    if N < 1:
        raise ValueError(f"tsmom_signal(): N 須 ≥ 1，目前 {N}")
    if "close" not in df.columns:
        raise ValueError("tsmom_signal(): df 缺少 close 欄位")

    close = df["close"]
    # past_return[t] 只用到 close[t] 與 close[t-N]，皆為 t(含)之前 → 無未來函數
    past_return = close / close.shift(N) - 1.0
    signal = (past_return > 0).astype(int)
    # 前 N 天（past_return 為 NaN）→ shift 後比較為 False → 已是 0，明確標示為空手
    signal[past_return.isna()] = 0
    signal.name = "signal"
    return signal
