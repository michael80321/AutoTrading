"""
共識引擎 — 動態權重投票
- 收集 18 席信號
- 用 EWMA 滾動更新每席權重
- 過濾通過後路由給執行層
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import logging
import numpy as np
from ..strategies.base import Signal, BotMetrics

logger = logging.getLogger(__name__)


@dataclass
class ConsensusResult:
    approved: bool
    side: str
    entry: float
    stop_loss: float
    take_profit: list[float]
    risk_pct: float
    contributors: list[str]
    schools_aligned: int
    total_weight: float
    rationale: str


class ConsensusEngine:
    """
    動態權重共識引擎
    新權重 = 0.7 × 近30天綜合分數 + 0.3 × 原始基礎權重
    """
    
    def __init__(
        self,
        min_aligned_schools: int = 3,
        min_total_weight: float = 1.5,
        min_backtest_winrate: float = 0.58,
        max_risk_per_trade_pct: float = 0.015,
        ewma_alpha: float = 0.7,  # 0.7 近期 + 0.3 基礎
    ):
        self.min_aligned_schools = min_aligned_schools
        self.min_total_weight = min_total_weight
        self.min_backtest_winrate = min_backtest_winrate
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.ewma_alpha = ewma_alpha
        
        # 基礎權重(根據學派長期歷史夏普)
        self.base_weights = {
            "SMC": 1.0, "拍賣理論": 1.0, "訂單流": 1.1, "鏈上": 0.9,
            "套利": 1.2, "傳統TA": 0.8, "量化統計": 1.0, "宏觀": 0.9,
            "情緒": 0.7, "AI 元學派": 1.3,
        }
        # 滾動更新的動態權重 bot_id -> weight
        self.dynamic_weights: dict[int, float] = {}
    
    def update_weights(self, metrics_snapshots: list[BotMetrics], bot_schools: dict[int, str]):
        """每日收盤後呼叫一次,根據近 30 天綜合分數更新動態權重"""
        for m in metrics_snapshots:
            school = bot_schools.get(m.bot_id, "Base")
            base = self.base_weights.get(school, 1.0)
            # 將綜合分數映射到 [0.3, 2.0] 區間
            perf_factor = 0.3 + m.composite_score * 1.7
            new_weight = self.ewma_alpha * perf_factor + (1 - self.ewma_alpha) * base
            self.dynamic_weights[m.bot_id] = round(new_weight, 3)
    
    def get_weight(self, bot_id: int, school: str) -> float:
        return self.dynamic_weights.get(bot_id, self.base_weights.get(school, 1.0))
    
    def aggregate(
        self,
        signals: list[Signal],
        bot_expectancies: dict[int, float | None],
        account_equity: float,
        symbol: str,
    ) -> Optional[ConsensusResult]:
        """
        對單一 symbol 聚合所有相關信號
        """
        relevant = [s for s in signals if s.symbol == symbol]
        if not relevant:
            return None

        long_signals = [s for s in relevant if s.side == "LONG"]
        short_signals = [s for s in relevant if s.side == "SHORT"]

        long_weight = sum(self.get_weight(s.bot_id, s.school) * s.confidence for s in long_signals)
        short_weight = sum(self.get_weight(s.bot_id, s.school) * s.confidence for s in short_signals)

        long_schools = len({s.school for s in long_signals})
        short_schools = len({s.school for s in short_signals})

        logger.info(
            f"[Consensus] {symbol} | LONG({long_schools}派 w={long_weight:.2f}) "
            f"SHORT({short_schools}派 w={short_weight:.2f}) | "
            f"訊號數 LONG={len(long_signals)} SHORT={len(short_signals)}"
        )

        # 決定方向（1.1x 門檻 + 無衝突快速通道）
        if long_weight > 0 and short_weight == 0:
            chosen, side, total_weight, schools_n = long_signals, "LONG", long_weight, long_schools
        elif short_weight > 0 and long_weight == 0:
            chosen, side, total_weight, schools_n = short_signals, "SHORT", short_weight, short_schools
        elif long_weight > short_weight * 1.1:
            chosen, side, total_weight, schools_n = long_signals, "LONG", long_weight, long_schools
        elif short_weight > long_weight * 1.1:
            chosen, side, total_weight, schools_n = short_signals, "SHORT", short_weight, short_schools
        else:
            logger.info(f"[Consensus] {symbol} ❌ 方向不明 (long={long_weight:.2f} short={short_weight:.2f}，差距未達 1.1x)")
            return None

        # 過濾門檻
        if schools_n < self.min_aligned_schools:
            logger.info(f"[Consensus] {symbol} ❌ 學派數不足 ({schools_n} < {self.min_aligned_schools}) — {[s.school for s in chosen]}")
            return None
        if total_weight < self.min_total_weight:
            logger.info(f"[Consensus] {symbol} ❌ 加權分不足 ({total_weight:.2f} < {self.min_total_weight})")
            return None
        # 每席正期望值門檻：backtest_expectancy > 0 才算有效投票席
        # None 表示回測樣本不足（< 10 筆），視為尚未驗證 → 不計入 qualified
        qualified = [s for s in chosen if (bot_expectancies.get(s.bot_id) or -1) > 0]
        if len(qualified) < self.min_aligned_schools:
            failed = [(s.bot_name, bot_expectancies.get(s.bot_id)) for s in chosen
                      if not ((bot_expectancies.get(s.bot_id) or -1) > 0)]
            logger.info(f"[Consensus] {symbol} ❌ 正期望值席數不足 ({len(qualified)}/{len(chosen)} 通過) 失敗: {failed}")
            return None

        logger.info(f"[Consensus] {symbol} ✅ {side} 通過！學派={schools_n} 加權={total_weight:.2f} 貢獻者={[s.bot_name for s in qualified]}")
        
        # 取信號平均進場 + 最緊的 SL + 加權 TP
        entry = float(np.mean([s.entry_price for s in qualified]))
        if side == "LONG":
            stop_loss = float(max(s.stop_loss for s in qualified))  # 最緊 = 最高
        else:
            stop_loss = float(min(s.stop_loss for s in qualified))
        
        # TP1 = 最近目標（LONG: 最低TP先觸發；SHORT: 最高TP先觸發）
        all_tps = [tp for s in qualified for tp in s.take_profit]
        tp_sorted = sorted(all_tps, reverse=(side == "SHORT"))
        take_profit = tp_sorted[:2]
        
        # 風險計算
        sl_dist_pct = abs(entry - stop_loss) / entry
        risk_pct = min(self.max_risk_per_trade_pct, self.max_risk_per_trade_pct * (total_weight / 3.0))
        
        return ConsensusResult(
            approved=True,
            side=side,
            entry=round(entry, 4),
            stop_loss=round(stop_loss, 4),
            take_profit=[round(tp, 4) for tp in take_profit],
            risk_pct=round(risk_pct, 4),
            contributors=[s.bot_name for s in qualified],
            schools_aligned=schools_n,
            total_weight=round(total_weight, 3),
            rationale=f"{schools_n} 派同向、加權分 {total_weight:.2f}、{len(qualified)} 席正期望值驗證",
        )
