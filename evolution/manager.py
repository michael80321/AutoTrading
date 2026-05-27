"""
進化機制 — 淘汰 / 沙盒 / 繁衍
週期 30 天結算一次:
- 後 15% → 進沙盒重訓
- 連兩週期墊底 → 永久退役
- 前 10% → 分裂繁衍 (±10% 參數變異),子代競爭 90 天
"""
import copy
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal
import numpy as np
from ..strategies.base import BaseStrategy, BotMetrics


@dataclass
class EvolutionEvent:
    timestamp: datetime
    bot_id: int
    bot_name: str
    action: Literal["promote_breed", "demote_sandbox", "retire", "resurrect", "sandbox_pass"]
    metrics: BotMetrics
    note: str


class EvolutionManager:
    """
    管理 18 席的生命週期
    """
    
    def __init__(
        self,
        cycle_days: int = 30,
        bottom_pct: float = 0.15,
        top_pct: float = 0.10,
        consecutive_bottom_to_retire: int = 2,
        sandbox_min_backtest_months: int = 18,
        breed_competition_days: int = 90,
    ):
        self.cycle_days = cycle_days
        self.bottom_pct = bottom_pct
        self.top_pct = top_pct
        self.consecutive_bottom_to_retire = consecutive_bottom_to_retire
        self.sandbox_min_backtest_months = sandbox_min_backtest_months
        self.breed_competition_days = breed_competition_days
        
        # 紀錄狀態
        self.bot_status: dict[int, str] = {}  # active / sandbox / breeding / retired
        self.consecutive_bottom_count: dict[int, int] = {}
        self.events: list[EvolutionEvent] = []
    
    def run_cycle(
        self,
        active_bots: list[BaseStrategy],
        metrics_map: dict[int, BotMetrics],
    ) -> list[EvolutionEvent]:
        """執行一次週期結算,回傳該週期所有事件"""
        cycle_events = []
        
        # 排名
        scored = [(b, metrics_map[b.bot_id]) for b in active_bots if b.bot_id in metrics_map]
        scored.sort(key=lambda x: x[1].composite_score, reverse=True)
        n = len(scored)
        top_n = max(1, int(n * self.top_pct))
        bot_n = max(1, int(n * self.bottom_pct))
        
        # 前段班 → 繁衍
        for bot, m in scored[:top_n]:
            event = EvolutionEvent(
                timestamp=datetime.now(),
                bot_id=bot.bot_id,
                bot_name=bot.name,
                action="promote_breed",
                metrics=m,
                note=f"綜合分 {m.composite_score:.3f} 進入前 {self.top_pct*100:.0f}%,觸發分裂繁衍",
            )
            cycle_events.append(event)
            self.bot_status[bot.bot_id] = "breeding"
            self.consecutive_bottom_count[bot.bot_id] = 0
        
        # 後段班 → 沙盒 / 退役
        for bot, m in scored[-bot_n:]:
            self.consecutive_bottom_count[bot.bot_id] = self.consecutive_bottom_count.get(bot.bot_id, 0) + 1
            if self.consecutive_bottom_count[bot.bot_id] >= self.consecutive_bottom_to_retire:
                action = "retire"
                note = f"連續 {self.consecutive_bottom_to_retire} 週期墊底,永久退役"
                self.bot_status[bot.bot_id] = "retired"
            else:
                action = "demote_sandbox"
                note = f"綜合分 {m.composite_score:.3f} 進入後 {self.bottom_pct*100:.0f}%,進入沙盒重訓"
                self.bot_status[bot.bot_id] = "sandbox"
            cycle_events.append(EvolutionEvent(
                timestamp=datetime.now(),
                bot_id=bot.bot_id,
                bot_name=bot.name,
                action=action,
                metrics=m,
                note=note,
            ))
        
        # 中段班保持 active,清零退役計數
        for bot, m in scored[top_n:-bot_n if bot_n > 0 else None]:
            self.bot_status[bot.bot_id] = "active"
            self.consecutive_bottom_count[bot.bot_id] = 0
        
        self.events.extend(cycle_events)
        return cycle_events
    
    def breed(self, parent: BaseStrategy, n_offspring: int = 2) -> list[BaseStrategy]:
        """
        分裂繁衍:複製父代為 2 個子代,各自施加 ±10% 參數變異
        子代獲得獨立 $300 USDT,競爭 90 天
        """
        offspring = []
        for i in range(n_offspring):
            child = copy.deepcopy(parent)
            child.bot_id = parent.bot_id * 100 + i + 1   # e.g. 1 → 101, 102
            child.name = f"{parent.name}-子{i+1}"
            child.params = parent._apply_mutation(mutation_rate=0.1)
            child.capital = 300.0
            child.trade_log = []
            child.equity_curve = [300.0]
            offspring.append(child)
        return offspring
    
    def sandbox_retrain(
        self,
        bot: BaseStrategy,
        historical_data: dict,
        backtest_fn,
    ) -> tuple[bool, dict]:
        """
        沙盒重訓流程:
        1. 用 >=18 個月歷史資料跑 walk-forward 優化
        2. 對每個參數做 grid/Bayes 搜尋,挑最高夏普組合
        3. 通過正期望值門檻才能復職
        回傳 (是否通過, 新參數)
        """
        from itertools import product
        
        # 簡化版 grid search — 實作時換成 Optuna
        original_params = bot.params.copy()
        best_score = -np.inf
        best_params = original_params
        
        # 對每個數值參數做 [0.8, 1.0, 1.2] 倍數搜尋
        numeric_keys = [k for k, v in original_params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        
        for combo in product([0.8, 1.0, 1.2], repeat=min(len(numeric_keys), 3)):
            trial_params = original_params.copy()
            for key, mult in zip(numeric_keys[:3], combo):
                v = original_params[key]
                new_v = v * mult
                trial_params[key] = int(round(new_v)) if isinstance(v, int) else new_v
            
            bot.params = trial_params
            result = backtest_fn(bot, historical_data, months=self.sandbox_min_backtest_months)
            
            if (result["positive_expectancy"]
                and result["sharpe"] > 1.0
                and result["sharpe"] > best_score):
                best_score = result["sharpe"]
                best_params = trial_params
        
        if best_score > 1.0:
            bot.params = best_params
            self.bot_status[bot.bot_id] = "active"
            self.consecutive_bottom_count[bot.bot_id] = 0
            self.events.append(EvolutionEvent(
                timestamp=datetime.now(),
                bot_id=bot.bot_id,
                bot_name=bot.name,
                action="sandbox_pass",
                metrics=None,
                note=f"沙盒重訓通過,新夏普 {best_score:.2f}",
            ))
            return True, best_params
        
        bot.params = original_params  # 還原
        return False, original_params
    
    def get_active_roster(self) -> list[int]:
        """回傳所有活躍機器人 ID"""
        return [bid for bid, status in self.bot_status.items() if status in ("active", "breeding")]
    
    def export_events(self) -> str:
        """匯出事件 JSON,給前端時間軸顯示"""
        return json.dumps([
            {
                "timestamp": e.timestamp.isoformat(),
                "bot_id": e.bot_id,
                "bot_name": e.bot_name,
                "action": e.action,
                "note": e.note,
                "composite_score": e.metrics.composite_score if e.metrics else None,
            }
            for e in self.events
        ], ensure_ascii=False, indent=2)
