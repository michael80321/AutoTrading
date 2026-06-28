"""
data_layer — 抓取 → 清理 → 切分。

關鍵約束：
- clean() 對缺值/重複/時間跳洞「必須報出來」，不可默默補。
- split() 嚴格時間切分，OOS 永遠在 IS 之後。
- 不做任何讓資料「看起來更好」的處理。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"

_OHLCV_COLS = ["open", "high", "low", "close", "volume"]


def _cache_path(symbol: str, timeframe: str) -> Path:
    safe = symbol.replace("/", "").upper()
    return _CACHE_DIR / f"{safe}_{timeframe}.csv"


def save_cache(df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(symbol, timeframe)
    df.to_csv(path)
    logger.info(f"已快取 {len(df)} 根 K 棒 → {path}")
    return path


def load_cache(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    logger.info(f"自快取載入 {len(df)} 根 K 棒 ← {path}")
    return df


def fetch(
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
    start: str | None = None,
    end: str | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """抓歷史 K 線，回傳 index 為 UTC timestamp 的 DataFrame（open/high/low/close/volume）。

    優先 ccxt 分頁抓取；失敗時若有快取則用快取，否則拋出明確錯誤。
    抓到的資料會寫入快取，之後離線也能跑回測。
    """
    last_err: Exception | None = None
    try:
        import ccxt  # 延遲匯入，沒裝也能用快取路徑

        exchange = ccxt.binance({"enableRateLimit": True})
        since = exchange.parse8601((start or "2017-08-17") + "T00:00:00Z")
        end_ms = exchange.parse8601((end + "T00:00:00Z")) if end else exchange.milliseconds()
        all_rows: list[list] = []
        limit = 1000
        tf_ms = exchange.parse_timeframe(timeframe) * 1000
        while since < end_ms:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not batch:
                break
            all_rows.extend(batch)
            since = batch[-1][0] + tf_ms
            if len(batch) < limit:
                break
        if all_rows:
            df = pd.DataFrame(all_rows, columns=["ts", *_OHLCV_COLS])
            df = df.drop_duplicates("ts")
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            df = df.set_index("ts").sort_index()
            df = df[df.index <= pd.to_datetime(end_ms, unit="ms", utc=True)]
            save_cache(df, symbol, timeframe)
            return df
        raise RuntimeError("ccxt 回傳空資料")
    except Exception as e:  # noqa: BLE001 — 任何抓取失敗都退回快取
        last_err = e
        logger.warning(f"ccxt 抓取失敗（{type(e).__name__}: {e}），嘗試快取…")

    if use_cache:
        cached = load_cache(symbol, timeframe)
        if cached is not None and len(cached) > 0:
            return cached

    raise RuntimeError(
        f"無法取得 {symbol} {timeframe} 歷史資料：網路抓取失敗且無快取。\n"
        f"原因：{last_err}\n"
        f"請在有網路的環境先跑一次（會自動寫入快取至 data_cache/），"
        f"或手動放一份 {_cache_path(symbol, timeframe).name} 到 data_cache/。"
    )


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """清理並『報出』所有資料品質問題，絕不默默補洞。

    - 重複時間戳：移除並記錄。
    - 缺值（OHLCV 任一為 NaN）：移除該列並記錄。
    - 時間跳洞：偵測並 warning 列出，但不插值（插值=製造假資料）。
    回傳 UTC 對齊、依時間排序的乾淨 DataFrame。
    """
    if df is None or len(df) == 0:
        raise ValueError("clean(): 輸入為空")

    df = df.copy()
    missing_cols = [c for c in _OHLCV_COLS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"clean(): 缺少必要欄位 {missing_cols}")

    # UTC 對齊
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    elif df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df.sort_index()

    # 重複時間戳
    dup_mask = df.index.duplicated(keep="first")
    if dup_mask.any():
        logger.warning(f"clean(): 發現 {int(dup_mask.sum())} 個重複時間戳，已移除（保留首筆）")
        df = df[~dup_mask]

    # 缺值
    na_mask = df[_OHLCV_COLS].isna().any(axis=1)
    if na_mask.any():
        bad_dates = df.index[na_mask][:10].tolist()
        logger.warning(
            f"clean(): 發現 {int(na_mask.sum())} 列含缺值，已移除（不插值）。範例日期: {bad_dates}"
        )
        df = df[~na_mask]

    # 非正數價格（資料錯誤）
    bad_price = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if bad_price.any():
        logger.warning(f"clean(): 發現 {int(bad_price.sum())} 列非正數價格，已移除")
        df = df[~bad_price]

    # 時間跳洞偵測（僅報告，不補）
    if len(df) > 2:
        deltas = df.index.to_series().diff().dropna()
        median_delta = deltas.median()
        gaps = deltas[deltas > median_delta * 1.5]
        if len(gaps) > 0:
            logger.warning(
                f"clean(): 偵測到 {len(gaps)} 處時間跳洞（K 棒不連續）。"
                f"中位間隔={median_delta}，最大缺口={gaps.max()}。"
                f"⚠️ 不自動插值；回測會把這些缺口當作正常相鄰 K 棒處理，請知悉。"
            )

    df = df[_OHLCV_COLS].astype(float)
    logger.info(f"clean(): 完成，輸出 {len(df)} 根乾淨 K 棒 "
                f"（{df.index[0].date()} ~ {df.index[-1].date()}）")
    return df


def split(df: pd.DataFrame, ratio: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """嚴格時間切分為 (In-Sample, Out-of-Sample)。OOS 永遠在 IS 之後。

    ratio = IS 佔比（預設 0.6）。
    """
    if not 0.1 < ratio < 0.95:
        raise ValueError(f"split(): ratio 須介於 0.1~0.95，目前 {ratio}")
    n = len(df)
    cut = int(n * ratio)
    is_df = df.iloc[:cut]
    oos_df = df.iloc[cut:]
    logger.info(
        f"split(): IS={len(is_df)} 根 ({is_df.index[0].date()}~{is_df.index[-1].date()})｜"
        f"OOS={len(oos_df)} 根 ({oos_df.index[0].date()}~{oos_df.index[-1].date()})"
    )
    return is_df, oos_df
