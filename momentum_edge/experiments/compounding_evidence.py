"""
複利的證據 — Shiller S&P 500 月線 1871 至今（155 年，含股息、通膨）。

回答一個問題：「什麼東西長期一直複利？」
方法：股息再投入的總報酬指數（Total Return），名目與實質（扣通膨）皆算，
      然後看不同持有年限的滾動視窗：勝率、最差情況、中位數年化。

誠實揭露：
- 這是「美國」的 155 年 —— 贏了兩次世界大戰的國家。國家層級的倖存者偏誤存在
  （反例：日本股市 1989 年高點後 34 年才回到原點）。
- 過去 155 年 ≠ 未來保證。這是人類手上最好的證據，不是預言。

執行： python -m momentum_edge.experiments.compounding_evidence
"""
from __future__ import annotations

import io
import urllib.request

import numpy as np
import pandas as pd

URL = "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"


def load_shiller() -> pd.DataFrame:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=60).read()
    df = pd.read_csv(io.BytesIO(raw))
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    df = df[["SP500", "Dividend", "Consumer Price Index"]].dropna(subset=["SP500"])
    df.columns = ["price", "dividend", "cpi"]
    # 近月股息/CPI 未公布時填 0 → 截到最後一筆完整數據為止（誠實截尾，不硬補）
    df = df.dropna()
    df = df[(df["dividend"] > 0) & (df["cpi"] > 0)]
    return df


def total_return_index(df: pd.DataFrame, real: bool) -> pd.Series:
    """股息再投入的總報酬指數。real=True 以 CPI 平減。"""
    p = df["price"].to_numpy()
    d = df["dividend"].to_numpy()  # 年化股息 → 每月 /12
    tr = np.empty(len(df))
    tr[0] = 1.0
    for i in range(1, len(df)):
        tr[i] = tr[i - 1] * (p[i] + d[i] / 12.0) / p[i - 1]
    s = pd.Series(tr, index=df.index)
    if real:
        s = s / df["cpi"] * df["cpi"].iloc[0]
    return s


def rolling_window_stats(tr: pd.Series, years: int) -> dict:
    """所有『持有 years 年』滾動視窗的：正報酬比例、最差/中位年化。"""
    m = years * 12
    if len(tr) <= m:
        return {}
    ratio = tr.values[m:] / tr.values[:-m]
    ann = ratio ** (1.0 / years) - 1.0
    return {
        "windows": len(ann),
        "pct_positive": float((ratio > 1.0).mean()),
        "worst_ann": float(ann.min()),
        "median_ann": float(np.median(ann)),
        "best_ann": float(ann.max()),
    }


def main() -> None:
    df = load_shiller()
    span_years = (df.index[-1] - df.index[0]).days / 365.25
    print("\n" + "=" * 84)
    print(f"  複利的證據 — S&P 500（Shiller 資料）{df.index[0].date()} ~ {df.index[-1].date()}"
          f"（{span_years:.0f} 年）")
    print("=" * 84)

    tr_nom = total_return_index(df, real=False)
    tr_real = total_return_index(df, real=True)
    px_only = df["price"] / df["price"].iloc[0]

    cagr = lambda s: (s.iloc[-1] / s.iloc[0]) ** (1 / span_years) - 1
    print(f"\n  ① 複利的來源分解（1 元變多少）")
    print(f"     只看價格（不含股息）      ：{px_only.iloc[-1]:>12,.0f} 元｜年化 {cagr(px_only)*100:.2f}%")
    print(f"     股息再投入（名目總報酬）  ：{tr_nom.iloc[-1]:>12,.0f} 元｜年化 {cagr(tr_nom)*100:.2f}%")
    print(f"     股息再投入＋扣通膨（實質）：{tr_real.iloc[-1]:>12,.0f} 元｜年化 {cagr(tr_real)*100:.2f}%")
    print(f"     → 股息再投入貢獻了絕大部分複利；『再投入』本身就是策略。")

    print(f"\n  ② 持有年限 vs 賺錢機率（實質報酬，扣通膨後；共 {len(tr_real)} 個月的滾動視窗）")
    print(f"     {'持有':>6s} {'視窗數':>7s} {'賺錢比例':>9s} {'最差年化':>9s} {'中位年化':>9s} {'最好年化':>9s}")
    for y in (1, 5, 10, 20, 30):
        st = rolling_window_stats(tr_real, y)
        if st:
            print(f"     {y:>4d}年 {st['windows']:>7d} {st['pct_positive']*100:>8.1f}% "
                  f"{st['worst_ann']*100:>+8.2f}% {st['median_ann']*100:>+8.2f}% {st['best_ann']*100:>+8.2f}%")

    # 成本對複利的破壞（用名目年化模擬每年抽走 x% 的費用/交易成本）
    base = cagr(tr_nom)
    print(f"\n  ③ 成本是負的複利（年化 {base*100:.2f}% 起算，40 年後 1 萬元變多少）")
    for drag_label, drag in [("0%（自己買指數ETF, 費用~0.1%內）", 0.001),
                             ("1%（主動基金管理費）", 0.01),
                             ("3%（頻繁交易的摩擦, 保守估）", 0.03)]:
        end = 10_000 * (1 + base - drag) ** 40
        print(f"     年損耗 {drag_label:<28s}：{end:>12,.0f} 元")

    print("\n  ④ 誠實警語")
    print("     ・這是『美國』的 155 年（贏兩次大戰的國家）。日本 1989 高點後 34 年才回本。")
    print("       → 解法不是不投資，是分散到全球（全球指數 ETF），別押單一國家。")
    print("     ・過去不保證未來。這是人類現有最好的證據，不是預言。")
    print("=" * 84 + "\n")


if __name__ == "__main__":
    main()
