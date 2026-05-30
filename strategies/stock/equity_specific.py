"""
美股池專屬 3 個學派 — 加密市場沒有對應物
- Earnings Hawk: 財報事件策略 (IV crush + post-earnings drift)
- Gamma Tide: 期權流 / Dealer Gamma 暴露
- Rotation Sage: 板塊輪動 (XLK/XLF/XLE/XLV/XLY 強弱)
"""
from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from ..base import BaseStrategy, Signal


class EarningsHawk(BaseStrategy):
    """
    美股 #16 · Earnings Hawk · 財報事件
    策略:財報前 3 天 IV 高峰賣權,財報後 PEAD (Post-Earnings Announcement Drift) 跟隨
    需要 context["earnings_calendar"] 和 context["iv_rank"]
    """
    SCHOOL = "財報事件"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "NFLX"]
    
    def _get_params(self) -> dict:
        return {
            "pre_earnings_days": 3,        # 財報前幾天進場做 IV
            "post_earnings_days_hold": 5,  # PEAD 持有期
            "min_iv_rank": 70,             # IV Rank 高才值得做 short vol
            "surprise_threshold_pct": 0.05, # 財報意外 > 5% 才追隨
            "rr_ratio": 2.0,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        earnings_cal = context.get("earnings_calendar", {})  # symbol -> next_earnings_date
        iv_rank = context.get("iv_rank")  # 0-100
        earnings_surprise = context.get("earnings_surprise_pct")  # 最近一次財報意外
        days_since_earnings = context.get("days_since_earnings")
        
        symbol = context.get("symbol", "AAPL")
        next_earnings = earnings_cal.get(symbol)
        if next_earnings is None or len(data) < 50:
            return None
        
        days_to_earnings = (next_earnings - datetime.now()).days if isinstance(next_earnings, datetime) else 999
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        # 場景 1:財報前,IV 飆高 → 做 short straddle (簡化為觀望,等財報後)
        if 0 < days_to_earnings <= p["pre_earnings_days"] and iv_rank and iv_rank >= p["min_iv_rank"]:
            # 暫不出單,標記為 watch
            return None
        
        # 場景 2:財報後 PEAD — 正向意外做多
        if (days_since_earnings is not None and 
            0 < days_since_earnings <= p["post_earnings_days_hold"] and
            earnings_surprise is not None):
            
            if earnings_surprise > p["surprise_threshold_pct"]:
                # 確認跳空後不破前低
                gap_low = data["low"].iloc[-days_since_earnings:].min()
                if price > gap_low * 1.005:
                    entry = price
                    sl = gap_low * 0.997
                    tp_dist = (entry - sl) * p["rr_ratio"]
                    return Signal(
                        bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                        symbol=symbol,
                        side="LONG", entry_price=entry, stop_loss=sl,
                        take_profit=[entry + tp_dist],
                        confidence=0.65,
                        timeframe=self.DEFAULT_TIMEFRAME,
                        timestamp=datetime.now(timezone.utc),
                        rationale=f"PEAD 正向漂移 — 財報超預期 {earnings_surprise*100:.1f}%,跳空守穩",
                    )
            elif earnings_surprise < -p["surprise_threshold_pct"]:
                gap_high = data["high"].iloc[-days_since_earnings:].max()
                if price < gap_high * 0.995:
                    entry = price
                    sl = gap_high * 1.003
                    tp_dist = (sl - entry) * p["rr_ratio"]
                    return Signal(
                        bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                        symbol=symbol,
                        side="SHORT", entry_price=entry, stop_loss=sl,
                        take_profit=[entry - tp_dist],
                        confidence=0.65,
                        timeframe=self.DEFAULT_TIMEFRAME,
                        timestamp=datetime.now(timezone.utc),
                        rationale=f"PEAD 負向漂移 — 財報不及預期 {earnings_surprise*100:.1f}%",
                    )
        return None


class GammaTide(BaseStrategy):
    """
    美股 #17 · Gamma Tide · 期權流
    Dealer Gamma 暴露 + 0DTE Pin Risk
    
    邏輯:
    - 正 Gamma 環境 (Dealers 做多 gamma) → 波動率被壓抑,均值回歸有效
    - 負 Gamma 環境 (Dealers 做空 gamma) → 波動率放大,追勢有效
    - GEX flip level 是關鍵支撐/壓力
    
    需要 context["dealer_gamma_exposure"], context["gex_flip_level"], context["max_pain"]
    """
    SCHOOL = "期權流"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA"]
    
    def _get_params(self) -> dict:
        return {
            "positive_gamma_threshold": 1e9,    # $1B positive GEX
            "negative_gamma_threshold": -5e8,   # -$500M negative GEX
            "pin_distance_pct": 0.005,          # 距離 max pain < 0.5% 視為 pin
            "rr_ratio_pos_gamma": 1.5,          # 均值回歸 RR 較低
            "rr_ratio_neg_gamma": 2.5,          # 追勢 RR 較高
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        gex = context.get("dealer_gamma_exposure")
        flip = context.get("gex_flip_level")
        max_pain = context.get("max_pain")
        is_opex_week = context.get("is_opex_week", False)
        
        if gex is None or len(data) < 50:
            return None
        
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        ma20 = data["close"].rolling(20).mean().iloc[-1]
        
        # 場景 A:正 Gamma 環境 + OpEx 週 + 接近 Max Pain → 做均值回歸到 Max Pain
        if (gex > p["positive_gamma_threshold"] and is_opex_week and max_pain is not None):
            distance_to_pain = (price - max_pain) / max_pain
            if abs(distance_to_pain) > p["pin_distance_pct"]:
                if distance_to_pain > 0:  # 價格高於 Max Pain,做空回到 pin
                    entry = price
                    sl = price + atr * 1.2
                    return Signal(
                        bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                        symbol=context.get("symbol", "SPY"),
                        side="SHORT", entry_price=entry, stop_loss=sl,
                        take_profit=[max_pain],
                        confidence=0.62,
                        timeframe=self.DEFAULT_TIMEFRAME,
                        timestamp=datetime.now(timezone.utc),
                        rationale=f"正 Gamma 環境 GEX=${gex/1e9:.1f}B,OpEx 週吸引至 Max Pain ${max_pain:.2f}",
                    )
                else:
                    entry = price
                    sl = price - atr * 1.2
                    return Signal(
                        bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                        symbol=context.get("symbol", "SPY"),
                        side="LONG", entry_price=entry, stop_loss=sl,
                        take_profit=[max_pain],
                        confidence=0.62,
                        timeframe=self.DEFAULT_TIMEFRAME,
                        timestamp=datetime.now(timezone.utc),
                        rationale=f"正 Gamma + OpEx,吸引上行至 Max Pain ${max_pain:.2f}",
                    )
        
        # 場景 B:負 Gamma 環境 + 突破 GEX flip → 追勢 (波動放大)
        if gex < p["negative_gamma_threshold"] and flip is not None:
            # 上穿 flip → 做多
            if price > flip * 1.002 and data["close"].iloc[-2] <= flip:
                entry = price
                sl = flip * 0.995
                tp_dist = (entry - sl) * p["rr_ratio_neg_gamma"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=context.get("symbol", "SPY"),
                    side="LONG", entry_price=entry, stop_loss=sl,
                    take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                    confidence=0.7,
                    timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(timezone.utc),
                    rationale=f"負 Gamma 環境 GEX=${gex/1e9:.1f}B,上破 GEX flip ${flip:.2f} 追勢",
                )
            if price < flip * 0.998 and data["close"].iloc[-2] >= flip:
                entry = price
                sl = flip * 1.005
                tp_dist = (sl - entry) * p["rr_ratio_neg_gamma"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=context.get("symbol", "SPY"),
                    side="SHORT", entry_price=entry, stop_loss=sl,
                    take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                    confidence=0.7,
                    timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(timezone.utc),
                    rationale=f"負 Gamma 環境,下破 GEX flip ${flip:.2f} 加速下跌",
                )
        return None


class RotationSage(BaseStrategy):
    """
    美股 #18 · Rotation Sage · 板塊輪動
    監測 11 個 SPDR 板塊 ETF 的相對強弱,做配對交易或單邊跟隨輪動
    
    邏輯:
    - 計算每個板塊 vs SPY 的 20D 相對強弱 (RS)
    - 連續 5 天 RS 排名上升 → 板塊輪入,做多領頭股
    - 連續 5 天 RS 排名下降 → 板塊輪出,做空尾端
    
    需要 context["sector_rs_ranks"]: dict{sector: rs_score}
    """
    SCHOOL = "板塊輪動"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB", "XLRE", "XLC"]
    
    def _get_params(self) -> dict:
        return {
            "rs_lookback": 20,
            "rs_rank_change_threshold": 3,    # 排名變動超過 3 位視為輪動
            "persistence_days": 5,            # 持續 5 天才確認
            "rr_ratio": 2.5,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        rs_ranks_history = context.get("sector_rs_ranks_history")  # list of {sector: rank} 每天一個
        
        if not rs_ranks_history or len(rs_ranks_history) < p["persistence_days"] + 1:
            return None
        if len(data) < 50:
            return None
        
        symbol = context.get("symbol", "XLK")
        
        # 計算該板塊近 N 天排名變化
        recent_ranks = [day_ranks.get(symbol, 6) for day_ranks in rs_ranks_history[-p["persistence_days"]:]]
        rank_old = rs_ranks_history[-p["persistence_days"]-1].get(symbol, 6)
        rank_now = recent_ranks[-1]
        rank_change = rank_old - rank_now  # 正 = 排名上升
        
        # 檢查趨勢一致性
        rank_trend_up = all(recent_ranks[i] >= recent_ranks[i+1] for i in range(len(recent_ranks)-1))
        rank_trend_dn = all(recent_ranks[i] <= recent_ranks[i+1] for i in range(len(recent_ranks)-1))
        
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        # 輪入 — 排名持續上升 + 突破 20D 高
        if rank_change >= p["rs_rank_change_threshold"] and rank_trend_up:
            recent_high = data["high"].iloc[-p["rs_lookback"]:-1].max()
            if price > recent_high:
                entry = price
                sl = price - atr * 2
                tp_dist = (entry - sl) * p["rr_ratio"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=symbol,
                    side="LONG", entry_price=entry, stop_loss=sl,
                    take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                    confidence=0.65,
                    timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(timezone.utc),
                    rationale=f"{symbol} 板塊輪入 — 排名從 {rank_old} 升至 {rank_now},突破 20D 高",
                )
        # 輪出 — 排名持續下降 + 跌破 20D 低
        if rank_change <= -p["rs_rank_change_threshold"] and rank_trend_dn:
            recent_low = data["low"].iloc[-p["rs_lookback"]:-1].min()
            if price < recent_low:
                entry = price
                sl = price + atr * 2
                tp_dist = (sl - entry) * p["rr_ratio"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=symbol,
                    side="SHORT", entry_price=entry, stop_loss=sl,
                    take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                    confidence=0.65,
                    timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(timezone.utc),
                    rationale=f"{symbol} 板塊輪出 — 排名從 {rank_old} 降至 {rank_now},跌破 20D 低",
                )
        return None
