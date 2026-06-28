"""
eval_layer.report — 輸出 CSV + 疊圖 + 三行警語。

報表頂端固定三行：
1. 使用的參數
2. 是否被改動過（過擬合警語）
3. 試了幾組參數（多重測試警語）

並把「回測(IS) vs 樣本外(OOS) vs 落差」三欄並排 —— 這欄是整個工具的靈魂。
主畫面最顯眼的是「扣成本後 vs Buy & Hold」；勝率被放在角落且加但書。
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 無頭環境
import matplotlib.pyplot as plt
import pandas as pd

from .. import config
from .metrics import METRIC_GLOSSARY, DECISION_METRICS, REFERENCE_METRICS

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

_PCT = {"total_return", "cagr", "max_drawdown", "win_rate"}


def _fmt(key: str, val) -> str:
    if isinstance(val, float) and key in _PCT:
        return f"{val*100:.2f}%"
    if isinstance(val, float):
        return f"{val:.3f}"
    return str(val)


def _warning_header(n_param_sets_tried: int) -> list[str]:
    """產生報表頂端三行警語。"""
    act = config.active_config()
    lines = []
    # 第 1 行：使用的參數
    lines.append(
        f"① 使用參數：SYMBOL={act['SYMBOL']} N={act['N']} "
        f"IS/OOS={act['IS_OOS_RATIO']:.0%}/{1-act['IS_OOS_RATIO']:.0%} "
        f"fee={act['FEE_ONE_WAY']*100:.2f}% slip={act['SLIPPAGE']*100:.3f}% "
        f"成交={act['EXECUTE_ON']} 做空={act['ALLOW_SHORT']} 槓桿={act['ALLOW_LEVERAGE']}"
    )
    # 第 2 行：是否被改動過
    modified = config.modified_params()
    if modified:
        diffs = ", ".join(f"{k}:{locked}→{active}" for k, (locked, active) in modified.items())
        lines.append(f"② ⚠️ 過擬合警語：你更動了參數（{diffs}）。這會增加過擬合風險，OOS 結果請更嚴格看待。")
    else:
        lines.append("② ✅ 參數為出廠鎖定值，未被更動。")
    # 第 3 行：試了幾組參數
    if n_param_sets_tried > 1:
        lines.append(
            f"③ ⚠️ 多重測試警語：你總共試了 {n_param_sets_tried} 組參數。"
            f"試越多組，其中一組『剛好看起來好』的機率就越高 —— 那可能是運氣不是 edge。"
        )
    else:
        lines.append("③ ✅ 多重測試：只用事先指定 (pre-registered) 的 1 組參數，無 data snooping。")
    return lines


def _build_metrics_table(rows: dict[str, dict]) -> pd.DataFrame:
    """rows: {欄位名 -> metrics dict}。回傳 index=指標、columns=各情境 的表。"""
    order = DECISION_METRICS + REFERENCE_METRICS
    data = {col: {m: rows[col].get(m) for m in order} for col in rows}
    df = pd.DataFrame(data)
    df = df.reindex(order)
    return df


def report(
    strat_is: dict,
    strat_oos: dict,
    strat_full: dict,
    bh_is: dict,
    bh_oos: dict,
    bh_full: dict,
    full_equity_strat: pd.Series,
    full_equity_bh: pd.Series,
    split_date,
    n_param_sets_tried: int = 1,
    tag: str = "BTCUSDT_N90",
) -> dict:
    """產生完整報表。strat_*/bh_* 為 metrics() 的輸出 dict。

    回傳 {csv_path, plot_path, gap_table}。
    """
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    header = _warning_header(n_param_sets_tried)

    # ── 終端輸出 ───────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("  動量 Edge 驗證報告 — 誠實版")
    print("=" * 78)
    for line in header:
        print("  " + line)
    print(f"  報酬口徑：{config.RETURN_CONVENTION}（單利）｜年化基準：{config.PERIODS_PER_YEAR} 天/年")
    print("-" * 78)

    # 主畫面：扣成本後總報酬 vs Buy & Hold（最重要）
    print("\n  ★ 主判準：扣成本後總報酬 vs Buy & Hold（贏不過 B&H = 沒有 edge）")
    for seg, s, b in [("樣本內 IS", strat_is, bh_is),
                      ("樣本外 OOS", strat_oos, bh_oos),
                      ("全期 FULL", strat_full, bh_full)]:
        beat = s["total_return"] - b["total_return"]
        verdict = "✅ 贏過 B&H" if beat > 0 else "❌ 輸給 B&H（無 edge）"
        print(f"    [{seg:9s}] 策略 {_fmt('total_return', s['total_return']):>9s} "
              f"｜ B&H {_fmt('total_return', b['total_return']):>9s} "
              f"｜ 超額 {beat*100:+.2f}% {verdict}")

    # ── 靈魂欄：回測(IS) vs 樣本外(OOS) vs 落差 ──────────────────
    print("\n  ★ 工具的靈魂：回測(IS) vs 樣本外(OOS) vs 落差（落差越大 = 回測越在騙人）")
    gap_rows = []
    for m in ["total_return", "max_drawdown", "sharpe"]:
        is_v, oos_v = strat_is[m], strat_oos[m]
        gap = is_v - oos_v
        gap_rows.append({"metric": m, "IS": is_v, "OOS": oos_v, "gap(IS-OOS)": gap})
        print(f"    {m:14s}｜回測IS {_fmt(m, is_v):>9s}｜樣本外OOS {_fmt(m, oos_v):>9s}"
              f"｜落差 {_fmt(m, gap):>9s}")
    gap_table = pd.DataFrame(gap_rows).set_index("metric")

    # ── 角落：僅供參考指標 ──────────────────────────────────────
    print("\n  ◦ 僅供參考（不可作為決策依據）：")
    print(f"    OOS 勝率 {strat_oos['win_rate']*100:.1f}%｜平均盈虧比 {strat_oos['avg_win_loss']}"
          f"  ← 勝率高 ≠ 賺錢，請看上面的總報酬與夏普")

    # ── 指標白話解讀 ────────────────────────────────────────────
    print("\n  ◦ 指標白話解讀：")
    for m in DECISION_METRICS + REFERENCE_METRICS:
        print(f"    - {METRIC_GLOSSARY[m]}")

    # ── CSV：IS/OOS/全期 × 策略/B&H 全部分開，不合併成單一漂亮數字 ──
    table = _build_metrics_table({
        "strategy_IS": strat_is, "BH_IS": bh_is,
        "strategy_OOS": strat_oos, "BH_OOS": bh_oos,
        "strategy_FULL": strat_full, "BH_FULL": bh_full,
    })
    csv_path = _OUTPUT_DIR / f"report_{tag}.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        for line in header:
            f.write(f"# {line}\n")
        f.write(f"# 報酬口徑: {config.RETURN_CONVENTION} (simple)；年化基準 {config.PERIODS_PER_YEAR}/年\n")
        f.write("# 注意：IS/OOS/全期分開呈現，未合併成單一數字。OOS 才是真正的答案。\n")
        table.to_csv(f)
    print(f"\n  📄 指標 CSV 已輸出 → {csv_path}")

    # ── 疊圖：策略 vs B&H 權益曲線 + IS/OOS 分界線 ───────────────
    plot_path = _OUTPUT_DIR / f"equity_{tag}.png"
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(full_equity_strat.index, full_equity_strat.values,
            label="TSMOM strategy (net of fees & slippage)", linewidth=1.6, color="#1f77b4")
    ax.plot(full_equity_bh.index, full_equity_bh.values,
            label="Buy & Hold benchmark", linewidth=1.6, color="#ff7f0e", alpha=0.85)
    ax.axvline(split_date, color="grey", linestyle="--", linewidth=1.2)
    ymin = min(full_equity_strat.min(), full_equity_bh.min())
    ax.text(split_date, ymin, "  <- IS | OOS ->", color="grey", va="bottom", fontsize=10)
    ax.set_title("Momentum Edge: TSMOM vs Buy & Hold (net of fees & slippage)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(plot_path, dpi=110)
    plt.close(fig)
    print(f"  📈 權益疊圖已輸出 → {plot_path}")
    print("=" * 78 + "\n")

    return {"csv_path": str(csv_path), "plot_path": str(plot_path), "gap_table": gap_table}
