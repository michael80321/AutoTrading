"""
SMC 學派 — Smart Money Concept
3 席:Alpha (流動性獵殺+OB)、Beta (BOS 趨勢)、Gamma (FVG 回填)
"""
from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime
from ..base import BaseStrategy, Signal


class SMCAlpha(BaseStrategy):
    """
    Bot #1 · 小騏 SMC-Alpha
    流動性獵殺 + Order Block 回測進場
    時框 15m/1H · BTC/ETH/SOL
    """
    SCHOOL = "SMC"
    DEFAULT_TIMEFRAME = "15m"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "swing_lookback": 20,           # 找擺動高低點窗口
            "ob_min_body_ratio": 0.6,       # OB K棒實體佔比
            "liquidity_buffer_pct": 0.001,  # 流動性掃過判定緩衝
            "rr_ratio": 2.5,                # 風報比
            "min_volume_zscore": 1.5,       # OB 形成需放量
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        lb = int(p["swing_lookback"])
        if len(data) < lb * 3:
            return None
        
        recent = data.iloc[-lb*2:]
        latest = data.iloc[-1]
        
        # 找最近的 swing high/low
        swing_high = recent["high"].rolling(lb).max().iloc[-lb]
        swing_low = recent["low"].rolling(lb).min().iloc[-lb]
        
        # 判定流動性掃過 (價格穿越 swing 後反向)
        liq_swept_high = data["high"].iloc[-3:-1].max() > swing_high * (1 + p["liquidity_buffer_pct"])
        liq_swept_low = data["low"].iloc[-3:-1].min() < swing_low * (1 - p["liquidity_buffer_pct"])
        
        # 成交量 z-score
        vol_z = (latest["volume"] - data["volume"].rolling(50).mean().iloc[-1]) / (data["volume"].rolling(50).std().iloc[-1] + 1e-9)
        
        # 找 Order Block — 最近一根大實體反向 K
        body = abs(data["close"] - data["open"])
        rng = data["high"] - data["low"]
        body_ratio = body / (rng + 1e-9)
        
        # 多單條件:掃過 low 後反轉 + OB 回測 + 放量
        if liq_swept_low and latest["close"] > latest["open"] and vol_z > p["min_volume_zscore"]:
            ob_candidates = data[(body_ratio > p["ob_min_body_ratio"]) & (data["close"] < data["open"])].iloc[-5:]
            if len(ob_candidates) > 0:
                ob = ob_candidates.iloc[-1]
                entry = latest["close"]
                sl = min(ob["low"], swing_low) * 0.999
                tp_dist = (entry - sl) * p["rr_ratio"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=context.get("symbol", "BTCUSDT"),
                    side="LONG", entry_price=entry, stop_loss=sl,
                    take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                    confidence=min(0.9, 0.5 + vol_z * 0.1),
                    timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(),
                    rationale=f"流動性掃過 swing low @ {swing_low:.2f},OB 回測 + 放量 z={vol_z:.2f}",
                )
        
        # 空單條件:掃過 high 後反轉
        if liq_swept_high and latest["close"] < latest["open"] and vol_z > p["min_volume_zscore"]:
            ob_candidates = data[(body_ratio > p["ob_min_body_ratio"]) & (data["close"] > data["open"])].iloc[-5:]
            if len(ob_candidates) > 0:
                ob = ob_candidates.iloc[-1]
                entry = latest["close"]
                sl = max(ob["high"], swing_high) * 1.001
                tp_dist = (sl - entry) * p["rr_ratio"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=context.get("symbol", "BTCUSDT"),
                    side="SHORT", entry_price=entry, stop_loss=sl,
                    take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                    confidence=min(0.9, 0.5 + vol_z * 0.1),
                    timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(),
                    rationale=f"流動性掃過 swing high @ {swing_high:.2f},OB 回測 + 放量 z={vol_z:.2f}",
                )
        return None


class SMCBeta(BaseStrategy):
    """
    Bot #2 · Orion SMC-Beta
    Break of Structure (BOS) 趨勢追蹤
    時框 4H/1D · BTC/ETH
    """
    SCHOOL = "SMC"
    DEFAULT_TIMEFRAME = "4H"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "bos_lookback": 30,
            "trend_ema": 50,
            "confirmation_candles": 2,
            "atr_period": 14,
            "atr_sl_mult": 1.8,
            "rr_ratio": 3.0,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < p["bos_lookback"] + p["trend_ema"]:
            return None
        
        # EMA 趨勢方向
        ema = data["close"].ewm(span=p["trend_ema"]).mean()
        trend_up = data["close"].iloc[-1] > ema.iloc[-1] and ema.iloc[-1] > ema.iloc[-10]
        trend_dn = data["close"].iloc[-1] < ema.iloc[-1] and ema.iloc[-1] < ema.iloc[-10]
        
        # ATR
        tr = pd.concat([
            data["high"] - data["low"],
            (data["high"] - data["close"].shift()).abs(),
            (data["low"] - data["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(p["atr_period"]).mean().iloc[-1]
        
        # BOS:突破前期高/低
        prev_high = data["high"].iloc[-p["bos_lookback"]:-p["confirmation_candles"]].max()
        prev_low = data["low"].iloc[-p["bos_lookback"]:-p["confirmation_candles"]].min()
        
        recent_closes = data["close"].iloc[-p["confirmation_candles"]:]
        
        if trend_up and (recent_closes > prev_high).all():
            entry = data["close"].iloc[-1]
            sl = entry - atr * p["atr_sl_mult"]
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist * 0.4, entry + tp_dist * 0.7, entry + tp_dist],
                confidence=0.72, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"BOS 多頭結構破前高 {prev_high:.2f},EMA{p['trend_ema']} 確認趨勢",
            )
        if trend_dn and (recent_closes < prev_low).all():
            entry = data["close"].iloc[-1]
            sl = entry + atr * p["atr_sl_mult"]
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist * 0.4, entry - tp_dist * 0.7, entry - tp_dist],
                confidence=0.72, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"BOS 空頭結構破前低 {prev_low:.2f}",
            )
        return None


class SMCGamma(BaseStrategy):
    """
    Bot #3 · Helix SMC-Gamma
    FVG (Fair Value Gap) 公平價值缺口回填
    時框 5m/15m · BTC perp
    """
    SCHOOL = "SMC"
    DEFAULT_TIMEFRAME = "5m"
    DEFAULT_UNIVERSE = ["BTCUSDT-PERP"]
    
    def _get_params(self) -> dict:
        return {
            "fvg_min_size_pct": 0.0015,
            "fvg_max_age": 50,
            "fill_tolerance": 0.0008,
            "rr_ratio": 2.0,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < p["fvg_max_age"] + 5:
            return None
        
        recent = data.iloc[-p["fvg_max_age"]:].reset_index(drop=True)
        latest_price = recent["close"].iloc[-1]
        
        # 找 FVG:三根 K,第一根 high < 第三根 low (bullish FVG) 或 第一根 low > 第三根 high (bearish FVG)
        bullish_fvgs = []
        bearish_fvgs = []
        for i in range(len(recent) - 3):
            c1, c3 = recent.iloc[i], recent.iloc[i+2]
            if c1["high"] < c3["low"]:
                gap_size = (c3["low"] - c1["high"]) / c1["high"]
                if gap_size > p["fvg_min_size_pct"]:
                    bullish_fvgs.append({"top": c3["low"], "bottom": c1["high"], "age": len(recent) - i})
            elif c1["low"] > c3["high"]:
                gap_size = (c1["low"] - c3["high"]) / c1["low"]
                if gap_size > p["fvg_min_size_pct"]:
                    bearish_fvgs.append({"top": c1["low"], "bottom": c3["high"], "age": len(recent) - i})
        
        # 多單:價格回到 bullish FVG 區域
        for fvg in bullish_fvgs:
            if fvg["bottom"] * (1 - p["fill_tolerance"]) <= latest_price <= fvg["top"] * (1 + p["fill_tolerance"]):
                entry = latest_price
                sl = fvg["bottom"] * 0.997
                tp_dist = (entry - sl) * p["rr_ratio"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=context.get("symbol", "BTCUSDT"),
                    side="LONG", entry_price=entry, stop_loss=sl,
                    take_profit=[entry + tp_dist],
                    confidence=0.6, timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(),
                    rationale=f"Bullish FVG [{fvg['bottom']:.2f}~{fvg['top']:.2f}] 回填進場",
                )
        for fvg in bearish_fvgs:
            if fvg["bottom"] * (1 - p["fill_tolerance"]) <= latest_price <= fvg["top"] * (1 + p["fill_tolerance"]):
                entry = latest_price
                sl = fvg["top"] * 1.003
                tp_dist = (sl - entry) * p["rr_ratio"]
                return Signal(
                    bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                    symbol=context.get("symbol", "BTCUSDT"),
                    side="SHORT", entry_price=entry, stop_loss=sl,
                    take_profit=[entry - tp_dist],
                    confidence=0.6, timeframe=self.DEFAULT_TIMEFRAME,
                    timestamp=datetime.now(),
                    rationale=f"Bearish FVG [{fvg['bottom']:.2f}~{fvg['top']:.2f}] 回填進場",
                )
        return None
