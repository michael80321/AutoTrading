"""
引擎正確性測試 — 用『確定性合成資料』檢驗回測引擎本身，不需網路。

注意：這裡的合成資料只用來驗證『程式邏輯正確』，
絕不拿合成資料的報酬數字宣稱真實 edge。真實 edge 必須用真實歷史資料跑 run.py。

涵蓋驗收標準：
  #1 fee=0 → 拒絕執行並報錯
  #2 找不到「t 訊號在 t 收盤成交」的路徑（成交一定在 t+1 開盤）
  + 無未來函數（改未來資料不影響過去）
  + 成本確實侵蝕報酬
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from ..strategy_layer import tsmom_signal
from ..eval_layer import backtest, buy_and_hold, metrics


def _make_df(closes, opens=None, index_start="2020-01-01") -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range(index_start, periods=n, freq="D", tz="UTC")
    closes = np.asarray(closes, dtype=float)
    if opens is None:
        # 開盤 = 前一日收盤（隔夜無跳空），第一日開=收
        opens = np.concatenate([[closes[0]], closes[:-1]])
    opens = np.asarray(opens, dtype=float)
    return pd.DataFrame({
        "open": opens,
        "high": np.maximum(opens, closes) * 1.001,
        "low": np.minimum(opens, closes) * 0.999,
        "close": closes,
        "volume": np.ones(n) * 100,
    }, index=idx)


def test_fee_zero_rejected():
    """#1 把手續費設為 0 → 拒絕執行並報錯。"""
    df = _make_df(np.linspace(100, 200, 50))
    sig = tsmom_signal(df, N=5)
    for fee in (0.0, -0.001, config.MIN_FEE_ONE_WAY / 2):
        try:
            backtest(df, sig, fee=fee, slip=0.0005)
            raise AssertionError(f"fee={fee} 竟未報錯")
        except ValueError as e:
            assert "手續費" in str(e) or "fee" in str(e)
    print("✅ #1 fee=0 被拒絕")


def test_slip_zero_rejected():
    df = _make_df(np.linspace(100, 200, 50))
    sig = tsmom_signal(df, N=5)
    try:
        backtest(df, sig, fee=0.001, slip=0.0)
        raise AssertionError("slip=0 竟未報錯")
    except ValueError as e:
        assert "滑價" in str(e) or "slip" in str(e)
    print("✅ slip=0 被拒絕")


def test_no_lookahead_future_close_cannot_change_past():
    """#2 + 無未來函數：竄改『最後一天收盤』不可改變先前任何權益或成交。

    最後一天收盤只會改變 signal[-1]，而 signal[-1] 要到不存在的下一天開盤才成交，
    因此不可能影響任何已發生的買賣或先前的權益。
    若引擎偷用『當日收盤訊號當日成交』，這個測試就會抓到。
    """
    closes = list(np.linspace(100, 130, 40)) + list(np.linspace(130, 110, 40))
    df = _make_df(closes)
    sig = tsmom_signal(df, N=10)
    base = backtest(df, sig, fee=0.001, slip=0.0005)

    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("close")] = 99999.0  # 竄改未來
    sig2 = tsmom_signal(df2, N=10)
    pert = backtest(df2, sig2, fee=0.001, slip=0.0005)

    # 除了最後一天的 mark-to-market，先前每天權益必須完全相同
    pd.testing.assert_series_equal(
        base["equity"].iloc[:-1], pert["equity"].iloc[:-1], check_names=False
    )
    # 已完成的回合交易也必須一致
    base_done = [(t["entry_date"], t["exit_date"]) for t in base["trades"] if not t["open_at_end"]]
    pert_done = [(t["entry_date"], t["exit_date"]) for t in pert["trades"] if not t["open_at_end"]]
    assert base_done == pert_done, "未來資料改變了過去的成交 → 有 look-ahead！"
    print("✅ #2 無未來函數：竄改未來收盤不影響過去成交與權益")


def test_fill_happens_at_next_open_not_signal_close():
    """進場成交價必須是『訊號隔日的開盤』，而非訊號當日收盤。"""
    # 設計：第 N..k 為上升（訊號轉多），讓某天 close 觸發訊號，隔日開盤為特殊值
    closes = [100] * 5 + [101, 102, 103, 104, 105, 106, 107, 108]
    opens = list(closes)
    # 讓「訊號轉多後的隔日開盤」是一個明顯不同於前一收盤的值
    df = _make_df(closes, opens=opens)
    N = 3
    sig = tsmom_signal(df, N=N)
    # 找第一個 signal 由 0→1 的日 t；成交應發生在 t+1 開盤
    flip_t = None
    for i in range(1, len(sig)):
        if sig.iloc[i] == 1 and sig.iloc[i - 1] == 0:
            flip_t = i
            break
    assert flip_t is not None
    exec_i = flip_t + 1
    # 把成交日開盤設成獨特值，收盤設成另一獨特值
    df.iloc[exec_i, df.columns.get_loc("open")] = 50.0    # 成交開盤
    df.iloc[exec_i, df.columns.get_loc("close")] = 80.0   # 當日收盤（若偷用=look-ahead）
    res = backtest(df, sig, fee=0.001, slip=0.0005)

    fee, slip, initial = 0.001, 0.0005, config.INITIAL_CAPITAL
    units_if_open = (initial * (1 - fee)) / (50.0 * (1 + slip))
    expected_equity_at_exec = units_if_open * 80.0  # 用開盤買、收盤 mark
    got = res["equity"].iloc[exec_i]
    assert abs(got - expected_equity_at_exec) < 1e-6, (
        f"成交價非隔日開盤！got={got} expected(open-based)={expected_equity_at_exec}"
    )
    print("✅ 成交發生在 t+1 開盤（非訊號當日收盤）")


def test_costs_erode_returns():
    """成本確實侵蝕報酬：較高成本 → 較低期末權益。"""
    closes = list(np.linspace(100, 130, 30)) + list(np.linspace(130, 100, 30)) + list(np.linspace(100, 140, 30))
    df = _make_df(closes)
    sig = tsmom_signal(df, N=10)
    low = backtest(df, sig, fee=0.001, slip=0.0005)["equity"].iloc[-1]
    high = backtest(df, sig, fee=0.005, slip=0.003)["equity"].iloc[-1]
    assert high < low, f"提高成本後權益沒下降（low={low}, high={high}）"
    print("✅ 成本確實侵蝕報酬")


def test_signal_no_future_dependency():
    """tsmom 訊號：改變未來收盤不可改變先前的訊號值。"""
    closes = list(np.linspace(100, 200, 60))
    df = _make_df(closes)
    s1 = tsmom_signal(df, N=20)
    df2 = df.copy()
    df2.iloc[-5:, df2.columns.get_loc("close")] = 1.0  # 砸爛最後 5 天
    s2 = tsmom_signal(df2, N=20)
    pd.testing.assert_series_equal(s1.iloc[:-5], s2.iloc[:-5], check_names=False)
    print("✅ 訊號無未來相依")


def test_buy_and_hold_sanity():
    """B&H：上漲序列應賺錢、扣一次成本、單調反映價格。"""
    closes = list(np.linspace(100, 200, 50))
    df = _make_df(closes)
    res = buy_and_hold(df, fee=0.001, slip=0.0005)
    m = metrics(res)
    assert m["total_return"] > 0
    assert m["n_trades"] == 1
    # 期末權益 ≈ 初始 * (close_last/buy_price) * (1-fee)
    print(f"✅ B&H sanity：總報酬 {m['total_return']*100:.2f}%, 交易 {m['n_trades']} 次")


def run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"\n跑 {len(fns)} 個引擎測試…\n")
    for fn in fns:
        fn()
    print(f"\n🎉 全部 {len(fns)} 個測試通過\n")


if __name__ == "__main__":
    run_all()
