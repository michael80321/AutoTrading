"""
回測引擎 — 18 個月 walk-forward 正期望值驗證
所有新策略 / 沙盒復職 / 繁衍子代上線實盤前必須通過
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from ..strategies.base import BaseStrategy, Signal


@dataclass
class BacktestResult:
    bot_id: int
    bot_name: str
    period_start: datetime
    period_end: datetime
    total_trades: int
    winning_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float          # 每筆期望值
    positive_expectancy: bool
    sharpe: float
    max_drawdown: float
    final_equity: float
    walk_forward_segments: int
    out_of_sample_consistency: float  # OOS 表現一致性
    
    def passed(self, min_winrate: float = 0.55, min_sharpe: float = 1.0) -> bool:
        """是否通過上線門檻"""
        return (
            self.positive_expectancy
            and self.win_rate >= min_winrate
            and self.sharpe >= min_sharpe
            and self.max_drawdown <= 0.25
            and self.total_trades >= 50  # 樣本數門檻
            and self.out_of_sample_consistency >= 0.6
        )


class BacktestEngine:
    """
    Walk-Forward 回測
    切 6 個段:每段 3 個月,前 2 個月 in-sample 後 1 個月 out-of-sample
    """
    
    def __init__(
        self,
        initial_capital: float = 300.0,
        fee_rate: float = 0.0004,
        slippage_pct: float = 0.0005,
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct
    
    def run(
        self,
        bot: BaseStrategy,
        data: pd.DataFrame,
        months: int = 18,
        walk_forward_segments: int = 6,
    ) -> BacktestResult:
        """
        執行 walk-forward 回測
        data 必須涵蓋至少 18 個月,且 index 為 datetime
        """
        if len(data) < 200:
            raise ValueError(f"資料不足,需 ≥ 200 根 K 棒,目前 {len(data)}")
        
        # 切分時段
        segment_len = len(data) // walk_forward_segments
        all_trades = []
        equity = self.initial_capital
        equity_curve = [equity]
        oos_returns_per_segment = []
        
        for seg_idx in range(walk_forward_segments):
            start = seg_idx * segment_len
            end = (seg_idx + 1) * segment_len
            in_sample = data.iloc[start:start + int(segment_len * 0.67)]
            out_sample = data.iloc[start + int(segment_len * 0.67):end]
            
            if len(out_sample) < 50:
                continue
            
            # OOS 模擬交易
            seg_start_equity = equity
            position = None
            
            for i in range(50, len(out_sample) - 1):
                window = out_sample.iloc[max(0, i-200):i+1]
                
                # 平倉檢查
                if position is not None:
                    nxt = out_sample.iloc[i+1]
                    closed_pnl = self._check_exit(position, nxt)
                    if closed_pnl is not None:
                        equity += closed_pnl
                        equity_curve.append(equity)
                        all_trades.append({
                            "side": position["side"],
                            "entry": position["entry"],
                            "exit": position.get("exit_price"),
                            "pnl": closed_pnl,
                            "pnl_pct": closed_pnl / seg_start_equity,
                        })
                        position = None
                
                # 開倉檢查
                if position is None:
                    signal = bot.signal(window)
                    if signal:
                        position = self._open_position(signal, equity)
            
            oos_return = (equity - seg_start_equity) / seg_start_equity if seg_start_equity > 0 else 0
            oos_returns_per_segment.append(oos_return)
        
        # 統計
        if not all_trades:
            return BacktestResult(
                bot_id=bot.bot_id, bot_name=bot.name,
                period_start=data.index[0] if isinstance(data.index, pd.DatetimeIndex) else datetime.now(),
                period_end=data.index[-1] if isinstance(data.index, pd.DatetimeIndex) else datetime.now(),
                total_trades=0, winning_trades=0, win_rate=0, avg_win=0, avg_loss=0,
                expectancy=0, positive_expectancy=False,
                sharpe=0, max_drawdown=0, final_equity=equity,
                walk_forward_segments=walk_forward_segments,
                out_of_sample_consistency=0,
            )
        
        df = pd.DataFrame(all_trades)
        wins = df[df["pnl"] > 0]
        losses = df[df["pnl"] <= 0]
        win_rate = len(wins) / len(df)
        avg_win = wins["pnl"].mean() if len(wins) > 0 else 0
        avg_loss = abs(losses["pnl"].mean()) if len(losses) > 0 else 0
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
        
        eq_series = pd.Series(equity_curve)
        returns = eq_series.pct_change().dropna()
        sharpe = np.sqrt(252) * returns.mean() / (returns.std() + 1e-9)
        
        running_max = eq_series.cummax()
        dd = (eq_series - running_max) / running_max
        max_dd = abs(dd.min())
        
        # OOS 一致性 = 正報酬段數 / 總段數
        positive_segs = sum(1 for r in oos_returns_per_segment if r > 0)
        oos_consistency = positive_segs / len(oos_returns_per_segment) if oos_returns_per_segment else 0
        
        return BacktestResult(
            bot_id=bot.bot_id, bot_name=bot.name,
            period_start=data.index[0] if isinstance(data.index, pd.DatetimeIndex) else datetime.now(),
            period_end=data.index[-1] if isinstance(data.index, pd.DatetimeIndex) else datetime.now(),
            total_trades=len(df),
            winning_trades=len(wins),
            win_rate=round(win_rate, 4),
            avg_win=round(avg_win, 4),
            avg_loss=round(avg_loss, 4),
            expectancy=round(expectancy, 4),
            positive_expectancy=expectancy > 0,
            sharpe=round(sharpe, 3),
            max_drawdown=round(max_dd, 4),
            final_equity=round(equity, 2),
            walk_forward_segments=walk_forward_segments,
            out_of_sample_consistency=round(oos_consistency, 3),
        )
    
    def _open_position(self, signal: Signal, equity: float) -> dict:
        risk_amount = equity * 0.015
        sl_dist = abs(signal.entry_price - signal.stop_loss)
        qty = risk_amount / sl_dist if sl_dist > 0 else 0
        slippage = signal.entry_price * self.slippage_pct
        entry_adj = signal.entry_price + slippage if signal.side == "LONG" else signal.entry_price - slippage
        return {
            "side": signal.side,
            "entry": entry_adj,
            "qty": qty,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "fees_paid": qty * entry_adj * self.fee_rate,
        }
    
    def _check_exit(self, position: dict, bar: pd.Series) -> float | None:
        """檢查止損止盈是否觸發"""
        if position["side"] == "LONG":
            if bar["low"] <= position["stop_loss"]:
                exit_price = position["stop_loss"]
                position["exit_price"] = exit_price
                pnl = (exit_price - position["entry"]) * position["qty"] - position["fees_paid"] * 2
                return pnl
            for tp in position["take_profit"]:
                if bar["high"] >= tp:
                    position["exit_price"] = tp
                    pnl = (tp - position["entry"]) * position["qty"] - position["fees_paid"] * 2
                    return pnl
        else:
            if bar["high"] >= position["stop_loss"]:
                exit_price = position["stop_loss"]
                position["exit_price"] = exit_price
                pnl = (position["entry"] - exit_price) * position["qty"] - position["fees_paid"] * 2
                return pnl
            for tp in position["take_profit"]:
                if bar["low"] <= tp:
                    position["exit_price"] = tp
                    pnl = (position["entry"] - tp) * position["qty"] - position["fees_paid"] * 2
                    return pnl
        return None
