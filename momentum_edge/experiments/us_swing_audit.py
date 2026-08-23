"""
美股波段打法歷史審計 — 同一套誠實流程，換成 S&P 500。

資料：S&P 500 指數真實日線 OHLC 2000-01 ~ 2020-04（vega-datasets 公開資料）。
      涵蓋網路泡沫、2008 金融海嘯、2020 疫情崩盤 —— 對趨勢策略最有利的年代。
      ⚠️ 誠實揭露：資料止於 2020-04，沒包含 2020-2026 的大牛市；
      趨勢策略在熊市多的年代表現最好，所以這份數據對波段打法是「偏有利」的測試。

成本：美股 ETF 等級 —— 單邊 0.05%（含 IBKR 手續費+點差）+ 0.05% 滑價。
      比加密（0.1%+0.05%）便宜一半，這也偏有利於頻繁交易。

成交：真實 OHLC → 訊號用 t 收盤，t+1『開盤』成交（比 next_close 更嚴謹）。

執行： python -m momentum_edge.experiments.us_swing_audit
"""
from __future__ import annotations

import io
import logging
import urllib.request

import pandas as pd

from .. import config
from ..data_layer.data import clean
from ..data_layer import split
from ..eval_layer import backtest, buy_and_hold, metrics
from .swing_audit import STRATEGIES

logging.basicConfig(level=logging.WARNING)

SP500_DAILY_URL = "https://raw.githubusercontent.com/vega/vega-datasets/main/data/sp500-2000.csv"

# 美股 ETF 等級成本（IBKR 手續費 + SPY 點差 + 滑價緩衝），保守抓
US_FEE = 0.0005   # 0.05% 單邊
US_SLIP = 0.0005  # 0.05%


def fetch_sp500_daily() -> pd.DataFrame:
    req = urllib.request.Request(SP500_DAILY_URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=60).read()
    df = pd.read_csv(io.BytesIO(raw))
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]].astype(float)
    return df


def main() -> None:
    df = clean(fetch_sp500_daily())
    is_df, oos_df = split(df, config.IS_OOS_RATIO)
    n_tried = len(STRATEGIES)

    print("\n" + "=" * 96)
    print(f"  美股波段打法歷史審計 — S&P 500 真實日線 {df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"  成本：單邊 {US_FEE*100:.2f}% + {US_SLIP*100:.2f}% 滑價（美股 ETF 等級）｜t+1 開盤成交｜long/flat")
    print(f"  IS {is_df.index[0].date()}~{is_df.index[-1].date()}（含網路泡沫+金融海嘯）｜"
          f"OOS {oos_df.index[0].date()}~{oos_df.index[-1].date()}")
    print(f"  ⚠️ 多重測試警語：一次測 {n_tried} 組。只能用來否決打法，不能挑組上實盤。")
    print(f"  ⚠️ 資料止於 2020-04（缺 2020-2026 牛市），且熊市多的年代對趨勢策略偏有利。")
    print("=" * 96)

    bh_is = metrics(buy_and_hold(is_df, fee=US_FEE, slip=US_SLIP, execute_on="next_open"), periods_per_year=252)
    bh_oos = metrics(buy_and_hold(oos_df, fee=US_FEE, slip=US_SLIP, execute_on="next_open"), periods_per_year=252)

    print(f"  {'策略':<14s} {'頻率(次/年)':>10s} │ {'IS報酬':>9s} {'IS超額':>9s} │ "
          f"{'OOS報酬':>9s} {'OOS超額':>9s} │ {'OOS回撤':>8s} {'OOS夏普':>8s} │ 判定")
    print("  " + "─" * 100)

    rows = []
    for name, fn in STRATEGIES.items():
        sig = fn(df)
        m_is = metrics(backtest(is_df, sig.loc[is_df.index], fee=US_FEE, slip=US_SLIP,
                                execute_on="next_open"), periods_per_year=252)
        m_oos = metrics(backtest(oos_df, sig.loc[oos_df.index], fee=US_FEE, slip=US_SLIP,
                                 execute_on="next_open"), periods_per_year=252)
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
                     "is_mdd": m_is["max_drawdown"],
                     "oos_beats_bh": ex_oos > 0})

    print("  " + "─" * 100)
    print(f"  {'Buy & Hold':<14s} {'0.0':>10s} │ {bh_is['total_return']*100:>8.1f}% {'—':>9s} │ "
          f"{bh_oos['total_return']*100:>8.1f}% {'—':>9s} │ "
          f"{bh_oos['max_drawdown']*100:>7.1f}% {bh_oos['sharpe']:>8.2f} │ 基準線")
    print(f"  （IS 段 B&H 最大回撤 {bh_is['max_drawdown']*100:.1f}% —— 金融海嘯腰斬再腰斬的年代）")

    winners = [r for r in rows if r["oos_beats_bh"]]
    print("\n  結論：")
    print(f"  ・{n_tried} 組中 OOS 贏過 B&H 的：{len(winners)} 組"
          + (f"（{', '.join(r['strategy'] for r in winners)}）" if winners else ""))

    out = pd.DataFrame(rows)
    path = config.__file__.replace("config.py", "output/us_swing_audit.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 美股(S&P500)波段審計；{n_tried} 組 data snooping，只能否決不能挑選\n")
        f.write(f"# 資料 {df.index[0].date()}~{df.index[-1].date()}；成本 {US_FEE}+{US_SLIP}；t+1 開盤成交\n")
        out.to_csv(f, index=False)
    print(f"\n  📄 明細已輸出 → {path}")
    print("=" * 96 + "\n")


if __name__ == "__main__":
    main()
