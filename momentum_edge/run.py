"""
動量 Edge 驗證工具 — 主流程（資料流第 8 節 1→8）。

執行：
    python -m momentum_edge.run                 # 用鎖定預設 N=90，pre-registered 單組
    python -m momentum_edge.run --symbol ETH/USDT
    python -m momentum_edge.run --no-fetch      # 只用快取（離線）

設計哲學：本工具不提供「掃 N 找最佳值」的旗標。那是過擬合製造機（見 Non-Goals）。
若你真的想看多組 N 的對照，--audit-Ns 會跑 {30,60,90} 但強制觸發多重測試警語，
且只在報表標明「僅供教育，不可拿來挑一組上實盤」。
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from . import config
from .data_layer import fetch, clean, split
from .strategy_layer import tsmom_signal
from .eval_layer import backtest, buy_and_hold, metrics, report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("momentum_edge")


def _detect_execute_on(df: pd.DataFrame) -> str:
    """close-only 來源（open==close）只能用 next_close 成交，否則 next_open。

    用 prev_close 當 open 會讓『t+1 開盤』退化成『t 收盤』= 偷看未來，故嚴禁。
    """
    if bool((df["open"] == df["close"]).all()):
        return "next_close"
    return config.EXECUTE_ON


def _run_one(df: pd.DataFrame, N: int, ratio: float) -> dict:
    """對單一參數 N 跑完整 IS/OOS/全期 回測 + 基準，回傳所有 metrics 與曲線。"""
    execute_on = _detect_execute_on(df)

    # 4. 訊號（用鎖定 N，全序列計算 → OOS 自帶暖身）
    signal = tsmom_signal(df, N=N)

    # 3. 切分
    is_df, oos_df = split(df, ratio=ratio)
    split_date = oos_df.index[0]

    # 5+6. 回測 + 基準（IS / OOS / 全期 各跑一次，分開；成交基準一致）
    strat_full = backtest(df, signal, execute_on=execute_on)
    bh_full = buy_and_hold(df, execute_on=execute_on)
    strat_is = backtest(is_df, signal.loc[is_df.index], execute_on=execute_on)
    bh_is = buy_and_hold(is_df, execute_on=execute_on)
    strat_oos = backtest(oos_df, signal.loc[oos_df.index], execute_on=execute_on)
    bh_oos = buy_and_hold(oos_df, execute_on=execute_on)

    # 7. 指標
    return {
        "split_date": split_date,
        "strat_is": metrics(strat_is), "bh_is": metrics(bh_is),
        "strat_oos": metrics(strat_oos), "bh_oos": metrics(bh_oos),
        "strat_full": metrics(strat_full), "bh_full": metrics(bh_full),
        "full_equity_strat": strat_full["equity"],
        "full_equity_bh": bh_full["equity"],
        "execute_on": execute_on,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="動量 Edge 驗證工具")
    parser.add_argument("--symbol", default=config.SYMBOL)
    parser.add_argument("--timeframe", default=config.TIMEFRAME)
    parser.add_argument("--start", default="2017-08-17")
    parser.add_argument("--end", default=None)
    parser.add_argument("--no-fetch", action="store_true", help="只用快取，不連網")
    parser.add_argument("--audit-Ns", action="store_true",
                        help="額外跑 N∈{30,60,90} 對照（強制觸發多重測試警語，僅供教育）")
    args = parser.parse_args(argv)

    # 倖存者偏誤控管：只允許白名單標的
    if args.symbol not in config.ALLOWED_SYMBOLS:
        logger.error(
            f"標的 {args.symbol} 不在白名單 {config.ALLOWED_SYMBOLS}。"
            f"第一版只測長期存在的大型標的，避免倖存者偏誤。"
        )
        return 2

    # 1+2. 抓取 + 清理
    try:
        if args.no_fetch:
            from .data_layer import load_cache
            raw = load_cache(args.symbol, args.timeframe)
            if raw is None:
                logger.error("--no-fetch 但無快取，請先在有網路時跑一次。")
                return 1
        else:
            raw = fetch(args.symbol, args.timeframe, args.start, args.end)
    except Exception as e:
        logger.error(f"資料取得失敗：{e}")
        return 1

    df = clean(raw)
    if len(df) < config.N + 60:
        logger.error(f"資料量不足（{len(df)} 根），無法穩健切分 IS/OOS。")
        return 1

    safe_tag = args.symbol.replace("/", "")

    if args.audit_Ns:
        # 多重測試示範：跑 3 組，但每組各自輸出，且警語會標明試了 3 組
        n_list = [30, 60, 90]
        logger.warning(f"--audit-Ns：將跑 {n_list} 三組，這是 data snooping 的示範，報表會警告。")
        for N in n_list:
            res = _run_one(df, N=N, ratio=config.IS_OOS_RATIO)
            report(
                res["strat_is"], res["strat_oos"], res["strat_full"],
                res["bh_is"], res["bh_oos"], res["bh_full"],
                res["full_equity_strat"], res["full_equity_bh"],
                res["split_date"], n_param_sets_tried=len(n_list),
                tag=f"{safe_tag}_N{N}_audit", execute_on_actual=res["execute_on"],
            )
        return 0

    # 預設：pre-registered 單組 N
    res = _run_one(df, N=config.N, ratio=config.IS_OOS_RATIO)
    report(
        res["strat_is"], res["strat_oos"], res["strat_full"],
        res["bh_is"], res["bh_oos"], res["bh_full"],
        res["full_equity_strat"], res["full_equity_bh"],
        res["split_date"], n_param_sets_tried=1,
        tag=f"{safe_tag}_N{config.N}", execute_on_actual=res["execute_on"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
