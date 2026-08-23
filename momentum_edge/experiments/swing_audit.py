"""
波段打法歷史審計 (swing audit) — 回答一個具體問題：

    「一週進出幾次的波段打法，扣掉成本後，歷史上撐不撐得住？」

⚠️ 這是探索性掃描（data snooping）：一次測多組規則，
   結果只能用來「否決」打法（OOS 都輸就是撐不住），
   不能用來「挑最好的一組上實盤」（那是過擬合製造機）。
   報表會誠實標明總共試了幾組。

測試的機械化波段代理（皆 long/flat、不做空、不槓桿）：
  A. 快速動量  TSMOM N ∈ {5, 10, 20}          — 追短線趨勢
  B. 突破      Donchian 20/10、55/20           — 創新高買進、破低出場
  C. 均線交叉  MA 10/50、20/100                — 經典波段濾網
  D. 逢跌買回  RSI<30 買 / RSI>55 出（200MA 多頭濾網） — 「看到大跌撿便宜」

全部：訊號用 t 收盤(含)前資料，t+1 收盤成交，扣 0.1% 手續費 + 0.05% 滑價。
資料：CoinMetrics 真實 BTC 日線。IS/OOS 60/40 嚴格分離。

執行： python -m momentum_edge.experiments.swing_audit
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .. import config
from ..data_layer import fetch, clean, split
from ..eval_layer import backtest, buy_and_hold, metrics

logging.basicConfig(level=logging.WARNING)

START = "2017-08-17"  # 與主工具一致：只用流動性成熟後的年代


# ── 訊號產生器（全部只用過去資料；回傳 0/1 目標部位）────────────────

def sig_tsmom(df: pd.DataFrame, n: int) -> pd.Series:
    past = df["close"] / df["close"].shift(n) - 1.0
    s = (past > 0).astype(int)
    s[past.isna()] = 0
    return s


def sig_donchian(df: pd.DataFrame, n_in: int, n_out: int) -> pd.Series:
    """收盤突破『前 n_in 天高點』進場；跌破『前 n_out 天低點』出場。
    高低點皆 shift(1)：不含當天，否則 close 永遠 = 當天 rolling max。"""
    hi = df["close"].rolling(n_in).max().shift(1)
    lo = df["close"].rolling(n_out).min().shift(1)
    close = df["close"].to_numpy()
    hi_v, lo_v = hi.to_numpy(), lo.to_numpy()
    pos, out = 0, np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if np.isnan(hi_v[i]) or np.isnan(lo_v[i]):
            out[i] = 0
            continue
        if pos == 0 and close[i] > hi_v[i]:
            pos = 1
        elif pos == 1 and close[i] < lo_v[i]:
            pos = 0
        out[i] = pos
    return pd.Series(out, index=df.index)


def sig_ma_cross(df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    sig = (f > s).astype(int)
    sig[f.isna() | s.isna()] = 0
    return sig


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-12))


def sig_dip_buy(df: pd.DataFrame, rsi_in: float, rsi_out: float, trend_ma: int = 200) -> pd.Series:
    """200MA 之上（多頭）等 RSI 超賣買進，RSI 回中性出場 —— 最接近『看到大跌撿便宜』。"""
    rsi = _rsi(df["close"])
    trend = df["close"] > df["close"].rolling(trend_ma).mean()
    rsi_v, trend_v = rsi.to_numpy(), trend.to_numpy()
    pos, out = 0, np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if i < trend_ma:
            out[i] = 0
            continue
        if pos == 0 and trend_v[i] and rsi_v[i] < rsi_in:
            pos = 1
        elif pos == 1 and (rsi_v[i] > rsi_out or not trend_v[i]):
            pos = 0
        out[i] = pos
    return pd.Series(out, index=df.index)


STRATEGIES: dict[str, callable] = {
    "動量 N=5":        lambda d: sig_tsmom(d, 5),
    "動量 N=10":       lambda d: sig_tsmom(d, 10),
    "動量 N=20":       lambda d: sig_tsmom(d, 20),
    "突破 20/10":      lambda d: sig_donchian(d, 20, 10),
    "突破 55/20":      lambda d: sig_donchian(d, 55, 20),
    "均線 10/50":      lambda d: sig_ma_cross(d, 10, 50),
    "均線 20/100":     lambda d: sig_ma_cross(d, 20, 100),
    "逢跌買 RSI30/55": lambda d: sig_dip_buy(d, 30, 55),
    "逢跌買 RSI35/60": lambda d: sig_dip_buy(d, 35, 60),
}


def main() -> None:
    df = clean(fetch(config.SYMBOL, "1d", start=START))
    is_df, oos_df = split(df, config.IS_OOS_RATIO)
    n_tried = len(STRATEGIES)

    print("\n" + "=" * 96)
    print("  波段打法歷史審計 — BTC 真實日線", f"{df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"  成本：單邊 {config.FEE_ONE_WAY*100:.2f}% 手續費 + {config.SLIPPAGE*100:.3f}% 滑價｜"
          f"t+1 收盤成交｜long/flat 無槓桿")
    print(f"  ⚠️ 多重測試警語：一次測了 {n_tried} 組規則。就算有一組 OOS 贏，也可能是運氣。")
    print(f"     這份審計只能用來『否決』打法（全輸=撐不住），不能用來『挑一組上實盤』。")
    print("=" * 96)

    bh_is = metrics(buy_and_hold(is_df, execute_on="next_close"))
    bh_oos = metrics(buy_and_hold(oos_df, execute_on="next_close"))

    hdr = (f"  {'策略':<14s} {'頻率(次/年)':>10s} │ {'IS報酬':>9s} {'IS超額':>9s} │ "
           f"{'OOS報酬':>9s} {'OOS超額':>9s} │ {'OOS回撤':>8s} {'OOS夏普':>8s} │ 判定")
    print(hdr)
    print("  " + "─" * 100)

    rows = []
    for name, fn in STRATEGIES.items():
        sig = fn(df)
        m_is = metrics(backtest(is_df, sig.loc[is_df.index], execute_on="next_close"))
        m_oos = metrics(backtest(oos_df, sig.loc[oos_df.index], execute_on="next_close"))
        ex_is = m_is["total_return"] - bh_is["total_return"]
        ex_oos = m_oos["total_return"] - bh_oos["total_return"]
        verdict = "✅ OOS贏B&H" if ex_oos > 0 else "❌ 輸B&H"
        print(f"  {name:<14s} {m_oos['trades_per_year']:>10.1f} │ "
              f"{m_is['total_return']*100:>8.1f}% {ex_is*100:>+8.1f}% │ "
              f"{m_oos['total_return']*100:>8.1f}% {ex_oos*100:>+8.1f}% │ "
              f"{m_oos['max_drawdown']*100:>7.1f}% {m_oos['sharpe']:>8.2f} │ {verdict}")
        rows.append({"strategy": name, "trades_per_year_oos": m_oos["trades_per_year"],
                     "is_return": m_is["total_return"], "is_excess": ex_is,
                     "oos_return": m_oos["total_return"], "oos_excess": ex_oos,
                     "oos_mdd": m_oos["max_drawdown"], "oos_sharpe": m_oos["sharpe"],
                     "oos_beats_bh": ex_oos > 0})

    print("  " + "─" * 100)
    print(f"  {'Buy & Hold':<14s} {'0.0':>10s} │ {bh_is['total_return']*100:>8.1f}% {'—':>9s} │ "
          f"{bh_oos['total_return']*100:>8.1f}% {'—':>9s} │ "
          f"{bh_oos['max_drawdown']*100:>7.1f}% {bh_oos['sharpe']:>8.2f} │ 基準線")

    winners = [r for r in rows if r["oos_beats_bh"]]
    freq_target = [r for r in rows if r["trades_per_year_oos"] >= 50]  # 「一週幾次」≈ ≥50 次/年
    print("\n  結論：")
    print(f"  ・{n_tried} 組中 OOS 贏過 B&H 的：{len(winners)} 組"
          + (f"（{', '.join(r['strategy'] for r in winners)}）" if winners else ""))
    print(f"  ・達到『一週幾次』頻率（≥50 次/年）的組別：{len(freq_target)} 組，"
          f"其中 OOS 贏 B&H 的：{sum(1 for r in freq_target if r['oos_beats_bh'])} 組")

    out = pd.DataFrame(rows)
    path = config.__file__.replace("config.py", "output/swing_audit.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 波段打法審計；一次測 {n_tried} 組（data snooping，只能否決不能挑選）\n")
        f.write(f"# 資料 {df.index[0].date()}~{df.index[-1].date()}；成本 {config.FEE_ONE_WAY}+{config.SLIPPAGE}；t+1 收盤成交\n")
        out.to_csv(f, index=False)
    print(f"\n  📄 明細已輸出 → {path}")
    print("=" * 96 + "\n")


if __name__ == "__main__":
    main()
