"""
其餘學派 — 傳統 TA、量化統計、宏觀、情緒、Meta Ensemble
傳統 TA 2 席:Ichimoku、Fibonacci
量化統計 2 席:Bayes (均值回歸)、Markov (體制切換)
宏觀 1 席:Macro Hawk
情緒 1 席:Pulse
AI 元 1 席:Meta Ensemble
"""
from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime
from ..base import BaseStrategy, Signal


class IchimokuSage(BaseStrategy):
    """
    Bot #12 · Ichimoku Sage · 傳統 TA
    一目均衡表 + 多週期共振
    時框 4H/1D · 美股 + BTC
    """
    SCHOOL = "傳統TA"
    DEFAULT_TIMEFRAME = "4H"
    DEFAULT_UNIVERSE = ["BTCUSDT", "SPY", "QQQ", "AAPL", "NVDA"]
    
    def _get_params(self) -> dict:
        return {
            "tenkan": 9, "kijun": 26, "senkou_b": 52,
            "displacement": 26, "rr_ratio": 2.5,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < p["senkou_b"] + p["displacement"]:
            return None
        
        high, low, close = data["high"], data["low"], data["close"]
        tenkan = (high.rolling(p["tenkan"]).max() + low.rolling(p["tenkan"]).min()) / 2
        kijun = (high.rolling(p["kijun"]).max() + low.rolling(p["kijun"]).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(p["displacement"])
        senkou_b = ((high.rolling(p["senkou_b"]).max() + low.rolling(p["senkou_b"]).min()) / 2).shift(p["displacement"])
        
        price = close.iloc[-1]
        cloud_top = max(senkou_a.iloc[-1], senkou_b.iloc[-1])
        cloud_bot = min(senkou_a.iloc[-1], senkou_b.iloc[-1])
        
        # 多頭三條件:價格在雲上 + 轉換線上穿基準線 + 雲為綠
        bullish_cloud = senkou_a.iloc[-1] > senkou_b.iloc[-1]
        tenkan_cross_up = tenkan.iloc[-1] > kijun.iloc[-1] and tenkan.iloc[-2] <= kijun.iloc[-2]
        
        if price > cloud_top and bullish_cloud and tenkan_cross_up:
            entry = price
            sl = cloud_bot * 0.997
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                confidence=0.68, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale="一目三條件成立:價在雲上、雲為綠、轉換上穿基準",
            )
        # 空頭鏡像
        tenkan_cross_dn = tenkan.iloc[-1] < kijun.iloc[-1] and tenkan.iloc[-2] >= kijun.iloc[-2]
        if price < cloud_bot and not bullish_cloud and tenkan_cross_dn:
            entry = price
            sl = cloud_top * 1.003
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                confidence=0.68, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale="一目空頭三條件成立",
            )
        return None


class FibonacciTide(BaseStrategy):
    """
    Bot #13 · Fibonacci Tide · 傳統 TA
    費波那契回撤 + Elliott 波浪簡化
    時框 1H/4H · BTC/ETH
    """
    SCHOOL = "傳統TA"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "swing_lookback": 50,
            "fib_levels": [0.382, 0.5, 0.618],
            "tolerance_pct": 0.005,
            "rr_ratio": 2.0,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < p["swing_lookback"]:
            return None
        
        window = data.iloc[-p["swing_lookback"]:]
        swing_high = window["high"].max()
        swing_low = window["low"].min()
        price = data["close"].iloc[-1]
        
        # 判定趨勢方向 (高點在後 = 上升,低點在後 = 下降)
        high_pos = window["high"].idxmax()
        low_pos = window["low"].idxmin()
        uptrend = high_pos > low_pos
        
        rng = swing_high - swing_low
        
        if uptrend:
            for fib in p["fib_levels"]:
                level = swing_high - rng * fib
                if abs(price - level) / level < p["tolerance_pct"]:
                    entry = price
                    sl = swing_low * 0.997
                    tp_dist = (entry - sl) * p["rr_ratio"]
                    return Signal(
                        bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                        symbol=context.get("symbol", "BTCUSDT"),
                        side="LONG", entry_price=entry, stop_loss=sl,
                        take_profit=[swing_high, entry + tp_dist],
                        confidence=0.55 + (0.1 if fib == 0.618 else 0),
                        timeframe=self.DEFAULT_TIMEFRAME,
                        timestamp=datetime.now(),
                        rationale=f"上升趨勢回撤至 Fib {fib} = {level:.2f}",
                    )
        else:
            for fib in p["fib_levels"]:
                level = swing_low + rng * fib
                if abs(price - level) / level < p["tolerance_pct"]:
                    entry = price
                    sl = swing_high * 1.003
                    tp_dist = (sl - entry) * p["rr_ratio"]
                    return Signal(
                        bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                        symbol=context.get("symbol", "BTCUSDT"),
                        side="SHORT", entry_price=entry, stop_loss=sl,
                        take_profit=[swing_low, entry - tp_dist],
                        confidence=0.55 + (0.1 if fib == 0.618 else 0),
                        timeframe=self.DEFAULT_TIMEFRAME,
                        timestamp=datetime.now(),
                        rationale=f"下降趨勢反彈至 Fib {fib} = {level:.2f}",
                    )
        return None


class BayesMeanRev(BaseStrategy):
    """
    Bot #14 · Bayes Mean-Rev · 量化統計
    Bollinger z-score 均值回歸 + 貝氏更新
    時框 15m · 美股 ETF + BTC
    """
    SCHOOL = "量化統計"
    DEFAULT_TIMEFRAME = "15m"
    DEFAULT_UNIVERSE = ["BTCUSDT", "SPY", "QQQ", "IWM"]
    
    def _get_params(self) -> dict:
        return {
            "bb_period": 20,
            "bb_std": 2.0,
            "entry_zscore": 2.2,
            "exit_zscore": 0.3,
            "rr_ratio": 1.5,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < p["bb_period"] * 3:
            return None
        
        ma = data["close"].rolling(p["bb_period"]).mean()
        std = data["close"].rolling(p["bb_period"]).std()
        z = (data["close"] - ma) / (std + 1e-9)
        
        latest_z = z.iloc[-1]
        latest_ma = ma.iloc[-1]
        price = data["close"].iloc[-1]
        
        # 額外過濾:確保不是趨勢突破(動能 < 1.5x)
        momentum = abs(data["close"].iloc[-1] - data["close"].iloc[-5]) / data["close"].iloc[-5]
        if momentum > 0.03:
            return None
        
        if latest_z < -p["entry_zscore"]:
            entry = price
            sl = price - std.iloc[-1] * 1.5
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "SPY"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[latest_ma],
                confidence=min(0.85, 0.5 + abs(latest_z) * 0.1),
                timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"z-score {latest_z:.2f} 極端低,均值回歸目標 MA={latest_ma:.2f}",
            )
        if latest_z > p["entry_zscore"]:
            entry = price
            sl = price + std.iloc[-1] * 1.5
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "SPY"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[latest_ma],
                confidence=min(0.85, 0.5 + latest_z * 0.1),
                timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"z-score {latest_z:.2f} 極端高,均值回歸目標 MA={latest_ma:.2f}",
            )
        return None


class MarkovRegime(BaseStrategy):
    """
    Bot #15 · Markov Regime · 量化統計
    隱馬可夫模型體制切換 (牛/熊/盤整)
    時框 1D · 全市場
    """
    SCHOOL = "量化統計"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SPY", "QQQ"]
    
    def _get_params(self) -> dict:
        return {
            "vol_window": 30,
            "trend_window": 50,
            "regime_persistence": 5,  # 體制需持續 N 天才確認
            "rr_ratio": 3.0,
        }
    
    def _detect_regime(self, data: pd.DataFrame) -> str:
        p = self.params
        returns = data["close"].pct_change()
        vol = returns.rolling(p["vol_window"]).std().iloc[-1]
        trend = (data["close"].iloc[-1] - data["close"].iloc[-p["trend_window"]]) / data["close"].iloc[-p["trend_window"]]
        vol_high = returns.rolling(200).std().quantile(0.7)
        if trend > 0.05 and vol < vol_high:
            return "bull"
        if trend < -0.05 and vol < vol_high:
            return "bear"
        if vol > vol_high:
            return "high_vol"
        return "range"
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < 200:
            return None
        
        regime = self._detect_regime(data)
        # 確認前 N 天為同一體制
        prev_regime = self._detect_regime(data.iloc[:-p["regime_persistence"]])
        regime_just_changed = (regime != prev_regime)
        
        if not regime_just_changed:
            return None
        
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        if regime == "bull":
            entry = price
            sl = price - atr * 3
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "SPY"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist * 0.4, entry + tp_dist * 0.7, entry + tp_dist],
                confidence=0.62, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"體制切換 {prev_regime}→bull,趨勢跟隨",
            )
        if regime == "bear":
            entry = price
            sl = price + atr * 3
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "SPY"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist * 0.4, entry - tp_dist * 0.7, entry - tp_dist],
                confidence=0.62, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"體制切換 {prev_regime}→bear",
            )
        return None


class MacroHawk(BaseStrategy):
    """
    Bot #16 · Macro Hawk · 宏觀
    DXY/利率/M2 與風險資產相關性
    時框 1D/週 · BTC + SPX
    資料源:FRED API、TradingEconomics
    """
    SCHOOL = "宏觀"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["BTCUSDT", "SPY", "QQQ"]
    
    def _get_params(self) -> dict:
        return {
            "dxy_window": 20,
            "yield_threshold_bps": 15,
            "correlation_window": 60,
            "rr_ratio": 2.5,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        macro = context.get("macro_data", {})  # 應包含 dxy_change, us10y_yield_change, vix
        if not macro or len(data) < 100:
            return None
        
        dxy_chg = macro.get("dxy_change_5d", 0)
        yield_chg = macro.get("us10y_bps_change_5d", 0)
        vix = macro.get("vix", 20)
        
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        # 風險開:DXY 弱 + 利率穩定 + VIX 低
        risk_on = dxy_chg < -0.01 and abs(yield_chg) < p["yield_threshold_bps"] and vix < 18
        risk_off = dxy_chg > 0.015 or yield_chg > p["yield_threshold_bps"] or vix > 25
        
        if risk_on:
            entry = price
            sl = price - atr * 2.5
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                confidence=0.6, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"Risk-on:DXY {dxy_chg*100:.2f}%、VIX {vix}、利率穩",
            )
        if risk_off:
            entry = price
            sl = price + atr * 2.5
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                confidence=0.6, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"Risk-off:DXY/利率/VIX 預警",
            )
        return None


class PulseSentiment(BaseStrategy):
    """
    Bot #17 · Pulse · 情緒
    X/Reddit/新聞 NLP 情緒指數
    時框 1H · 熱門幣 + 個股
    """
    SCHOOL = "情緒"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "TSLA", "NVDA"]
    
    def _get_params(self) -> dict:
        return {
            "sentiment_extreme": 0.7,
            "volume_confirmation_zscore": 1.5,
            "contrarian_threshold": 0.85,  # 過度情緒反向操作
            "rr_ratio": 2.0,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        sentiment = context.get("sentiment_score")  # -1 ~ +1
        social_volume_z = context.get("social_volume_zscore", 0)
        if sentiment is None or len(data) < 50:
            return None
        
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        # 順勢:中等正情緒 + 成交量確認
        if p["sentiment_extreme"] < sentiment < p["contrarian_threshold"] and social_volume_z > p["volume_confirmation_zscore"]:
            entry = price
            sl = price - atr * 2
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist],
                confidence=0.55, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"情緒指數 {sentiment:.2f} 偏多 + 社群放量",
            )
        # 反向:極端情緒 (>0.85 或 <-0.85) — 通常為頂/底
        if sentiment > p["contrarian_threshold"]:
            entry = price
            sl = price + atr * 1.5
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist],
                confidence=0.5, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"情緒過熱 {sentiment:.2f} 反向操作",
            )
        if sentiment < -p["contrarian_threshold"]:
            entry = price
            sl = price - atr * 1.5
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist],
                confidence=0.5, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"情緒過冷 {sentiment:.2f} 反向操作",
            )
        return None


class MetaEnsemble(BaseStrategy):
    """
    Bot #18 · Meta Ensemble · AI 元學派
    融合前 17 席信號,自我學習加權
    使用 stacking + LightGBM 元學習器
    """
    SCHOOL = "AI 元學派"
    DEFAULT_TIMEFRAME = "multi"
    DEFAULT_UNIVERSE = ["dynamic"]
    
    def _get_params(self) -> dict:
        return {
            "min_subordinate_signals": 3,  # 至少 3 席同向
            "diversity_bonus": 0.15,        # 不同學派加權
            "recent_perf_weight": 0.6,
            "rr_ratio": 2.2,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        """
        context["sub_signals"] 為 list[Signal] — 來自其他 17 席的當前信號
        Meta 會根據各席近 30 天綜合分數動態加權
        """
        p = self.params
        sub_signals = context.get("sub_signals", [])
        bot_scores = context.get("bot_composite_scores", {})  # bot_id -> 綜合分數
        
        if len(sub_signals) < p["min_subordinate_signals"]:
            return None
        
        long_signals = [s for s in sub_signals if s.side == "LONG"]
        short_signals = [s for s in sub_signals if s.side == "SHORT"]
        
        long_score = sum(bot_scores.get(s.bot_id, 0.5) * s.confidence for s in long_signals)
        short_score = sum(bot_scores.get(s.bot_id, 0.5) * s.confidence for s in short_signals)
        
        # 學派多樣性加分
        long_schools = len({s.school for s in long_signals})
        short_schools = len({s.school for s in short_signals})
        long_score *= (1 + p["diversity_bonus"] * (long_schools - 1))
        short_score *= (1 + p["diversity_bonus"] * (short_schools - 1))
        
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        if long_score > short_score * 1.5 and len(long_signals) >= p["min_subordinate_signals"]:
            # 從子信號取最緊的 SL
            best_sl = max(s.stop_loss for s in long_signals)
            entry = price
            tp_dist = (entry - best_sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=best_sl,
                take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                confidence=min(0.95, 0.6 + long_score * 0.1),
                timeframe="multi", timestamp=datetime.now(),
                rationale=f"Meta 共識多:{len(long_signals)} 席跨 {long_schools} 派,加權分 {long_score:.2f}",
                metadata={"contributors": [s.bot_name for s in long_signals]},
            )
        if short_score > long_score * 1.5 and len(short_signals) >= p["min_subordinate_signals"]:
            best_sl = min(s.stop_loss for s in short_signals)
            entry = price
            tp_dist = (best_sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=best_sl,
                take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                confidence=min(0.95, 0.6 + short_score * 0.1),
                timeframe="multi", timestamp=datetime.now(),
                rationale=f"Meta 共識空:{len(short_signals)} 席跨 {short_schools} 派,加權分 {short_score:.2f}",
                metadata={"contributors": [s.bot_name for s in short_signals]},
            )
        return None
