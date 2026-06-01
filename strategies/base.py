"""
Base Strategy Class — 所有 18 席分析師繼承此類
定義統一介面:signal()、score()、evolve()、backtest()
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """單一交易信號"""
    bot_id: int
    bot_name: str
    school: str
    symbol: str
    side: Literal["LONG", "SHORT", "FLAT"]
    entry_price: float
    stop_loss: float
    take_profit: list[float]   # 支援分批止盈 [tp1, tp2, ...]
    confidence: float          # 0~1
    timeframe: str
    timestamp: datetime
    rationale: str             # 給聊天室用的人類可讀說明
    metadata: dict = field(default_factory=dict)


@dataclass
class BotMetrics:
    """機器人績效快照"""
    bot_id: int
    win_rate: float
    sharpe: float
    max_drawdown: float
    pnl_pct: float
    monthly_stability: float   # 月報酬標準差倒數
    composite_score: float     # 綜合分數
    total_trades: int
    period_days: int


class BaseStrategy(ABC):
    """
    所有 18 席分析師的基底類別
    每個子類必須實作:_generate_signal、_get_params、_apply_mutation
    """
    SCHOOL: str = "Base"
    DEFAULT_TIMEFRAME: str = "1H"
    DEFAULT_UNIVERSE: list[str] = []
    
    def __init__(
        self,
        bot_id: int,
        name: str,
        initial_capital: float = 300.0,
        fee_rate: float = 0.0004,            # 0.04% taker
        max_risk_per_trade: float = 0.015,   # 單筆 1.5%
    ):
        self.bot_id = bot_id
        self.name = name
        self.capital = initial_capital
        self.fee_rate = fee_rate
        self.max_risk_per_trade = max_risk_per_trade
        self.params: dict = self._get_params()
        self.trade_log: list[dict] = []
        self.equity_curve: list[float] = [initial_capital]
    
    @abstractmethod
    def _get_params(self) -> dict:
        """子類定義策略參數,供進化機制變異使用"""
        ...
    
    @abstractmethod
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        """
        核心信號邏輯
        data: OHLCV DataFrame (含必要的衍生欄位)
        context: 跨機器人共享上下文(聊天室訊息、其他學派信號等)
        """
        ...
    
    def signal(self, data: pd.DataFrame, context: dict | None = None) -> Optional[Signal]:
        """對外統一入口，含風控過濾"""
        if len(data) < 200:
            return None
        sig = self._generate_signal(data, context or {})
        if sig is None:
            return None
        # 風控：止損距離 0.3%–5%
        sl_dist = abs(sig.entry_price - sig.stop_loss) / sig.entry_price
        if not (0.003 <= sl_dist <= 0.05):
            logger.debug(
                f"[{self.name}] {sig.symbol} SL 距離 {sl_dist*100:.2f}% 超出 0.3-5% 範圍，訊號丟棄"
            )
            return None
        return sig
    
    def compute_metrics(self, period_days: int = 30) -> BotMetrics:
        """計算當前績效"""
        if len(self.trade_log) < 5:
            # 無足夠歷史時給予中性預設值，讓新機器人可以參與共識
            return BotMetrics(self.bot_id, 0.6, 0, 0, 0, 0, 0.3, len(self.trade_log), period_days)
        
        df = pd.DataFrame(self.trade_log)
        wins = df[df["pnl"] > 0]
        win_rate = len(wins) / len(df)
        
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        sharpe = np.sqrt(252) * returns.mean() / (returns.std() + 1e-9)
        
        eq = pd.Series(self.equity_curve)
        running_max = eq.cummax()
        drawdown = (eq - running_max) / running_max
        max_dd = abs(drawdown.min())
        
        pnl_pct = (eq.iloc[-1] - eq.iloc[0]) / eq.iloc[0]
        
        # 月度穩定性 = 1 / (月報酬標準差 + 1e-3)
        monthly_returns = returns.resample("ME").sum() if isinstance(returns.index, pd.DatetimeIndex) else returns
        stability = 1.0 / (monthly_returns.std() + 1e-3)
        
        # 綜合分數
        norm_sharpe = np.clip(sharpe / 3.0, 0, 1)
        composite = (
            0.35 * norm_sharpe
            + 0.25 * win_rate
            + 0.20 * (1 - max_dd)
            + 0.20 * np.clip(stability / 10, 0, 1)
        )
        
        return BotMetrics(
            bot_id=self.bot_id,
            win_rate=round(win_rate, 4),
            sharpe=round(sharpe, 3),
            max_drawdown=round(max_dd, 4),
            pnl_pct=round(pnl_pct, 4),
            monthly_stability=round(stability, 3),
            composite_score=round(composite, 4),
            total_trades=len(df),
            period_days=period_days,
        )
    
    def _apply_mutation(self, mutation_rate: float = 0.1) -> dict:
        """繁衍時對參數施加 ±10% 隨機變異"""
        new_params = {}
        for k, v in self.params.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                noise = np.random.uniform(-mutation_rate, mutation_rate)
                new_v = v * (1 + noise)
                if isinstance(v, int):
                    new_v = max(1, int(round(new_v)))
                new_params[k] = new_v
            else:
                new_params[k] = v
        return new_params
    
    def position_size(self, entry: float, stop: float) -> float:
        """凱利簡化版 — 以單筆風險上限反推倉位"""
        risk_amount = self.capital * self.max_risk_per_trade
        sl_distance = abs(entry - stop)
        if sl_distance == 0:
            return 0
        return risk_amount / sl_distance
