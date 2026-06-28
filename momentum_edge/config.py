"""
中央配置 — 預設「鎖死」。
這個工具的核心價值之一是「不鼓勵調參數」。所有預設值都刻意保守。
若你更動了任何鎖定參數，report 會在報表頂端印出過擬合警語。

設計哲學提醒：如果你很想把成本調低、把 N 多掃幾組、把不做空拿掉，
讓曲線好看一點 —— 停下來。那個衝動就是上次賠錢的衝動。
"""

# ── 鎖定參數（要改請改這裡，工具會偵測並警告）─────────────────
SYMBOL: str = "BTC/USDT"
TIMEFRAME: str = "1d"
N: int = 90                 # 動量回看天數，預設鎖死
IS_OOS_RATIO: float = 0.6   # 前 60% 為樣本內 (In-Sample)
FEE_ONE_WAY: float = 0.001  # 0.1% 單邊手續費，不可為 0
SLIPPAGE: float = 0.0005    # 0.05% 滑價緩衝，不可為 0
ALLOW_SHORT: bool = False   # 第一版禁止做空
ALLOW_LEVERAGE: bool = False  # 第一版禁止槓桿
EXECUTE_ON: str = "next_open"  # t+1 開盤成交，防 look-ahead

INITIAL_CAPITAL: float = 10_000.0
PERIODS_PER_YEAR: int = 365     # 加密貨幣全年無休，年化用 365
RETURN_CONVENTION: str = "simple"  # 報酬口徑統一用單利（simple），報表會註明

# ── 規範驗證的標的白名單（控管倖存者偏誤）────────────────────
# 只測長期存在的大型標的，不碰已下市/暴死小幣。
ALLOWED_SYMBOLS = ("BTC/USDT", "ETH/USDT")

# ── 不可動的工具良心：成本歸零防呆 ───────────────────────────
MIN_FEE_ONE_WAY = 1e-9   # 低於此視為「試圖把成本設為 0」→ 拒絕執行
MIN_SLIPPAGE = 1e-9

# ── 鎖定基準快照（用於偵測使用者是否動過參數）─────────────────
# 這是「出廠預設」的硬編碼副本。report 會拿 active 值跟它比對。
# 若你只改了上面的變數而沒動這個 dict，工具就能偵測到差異並警告。
LOCKED_DEFAULTS = {
    "SYMBOL": "BTC/USDT",
    "TIMEFRAME": "1d",
    "N": 90,
    "IS_OOS_RATIO": 0.6,
    "FEE_ONE_WAY": 0.001,
    "SLIPPAGE": 0.0005,
    "ALLOW_SHORT": False,
    "ALLOW_LEVERAGE": False,
    "EXECUTE_ON": "next_open",
}


def active_config() -> dict:
    """目前實際生效的參數，供 report 比對與印出。"""
    return {
        "SYMBOL": SYMBOL,
        "TIMEFRAME": TIMEFRAME,
        "N": N,
        "IS_OOS_RATIO": IS_OOS_RATIO,
        "FEE_ONE_WAY": FEE_ONE_WAY,
        "SLIPPAGE": SLIPPAGE,
        "ALLOW_SHORT": ALLOW_SHORT,
        "ALLOW_LEVERAGE": ALLOW_LEVERAGE,
        "EXECUTE_ON": EXECUTE_ON,
    }


def modified_params() -> dict:
    """回傳被改動過的參數 {key: (locked, active)}，沒動則空 dict。"""
    act = active_config()
    return {k: (v, act[k]) for k, v in LOCKED_DEFAULTS.items() if act[k] != v}
