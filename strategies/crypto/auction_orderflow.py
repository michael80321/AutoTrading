"""
拍賣理論 (Auction Theory) 與訂單流 (Order Flow) 學派
拍賣 2 席:Volterra (Value Area)、Athena (Composite Profile)
訂單流 2 席:Tempest (Footprint Delta)、Riptide (CVD 背離)
"""
from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from ..base import BaseStrategy, Signal


class VolterraAuction(BaseStrategy):
    """
    Bot #4 · Volterra · 拍賣理論
    Value Area + POC 均值回歸,跨加密與美股期指
    時框 1H/4H · ES/NQ futures + BTC
    """
    SCHOOL = "拍賣理論"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ES1!", "NQ1!"]
    
    def _get_params(self) -> dict:
        return {
            "profile_window": 100,      # 計算 Volume Profile 的 K 棒數
            "value_area_pct": 0.70,     # Value Area 包含成交量比例
            "reversion_threshold": 0.5, # 偏離 VAH/VAL 多少標準差才進場
            "rr_ratio": 1.8,
            "atr_period": 14,
        }
    
    def _calc_volume_profile(self, df: pd.DataFrame, bins: int = 50):
        """回傳 POC、VAH、VAL"""
        prices = df["close"].values
        vols = df["volume"].values
        hist, edges = np.histogram(prices, bins=bins, weights=vols)
        poc_idx = hist.argmax()
        poc = (edges[poc_idx] + edges[poc_idx+1]) / 2
        
        total_vol = hist.sum()
        target = total_vol * self.params["value_area_pct"]
        cum = hist[poc_idx]
        lo, hi = poc_idx, poc_idx
        while cum < target and (lo > 0 or hi < len(hist) - 1):
            can_left = lo > 0
            can_right = hi < len(hist) - 1
            left = hist[lo - 1] if can_left else -np.inf
            right = hist[hi + 1] if can_right else -np.inf
            # 只往實際可移動的方向擴張，避免 lo/hi 越界造成無窮迴圈
            if can_left and (not can_right or left >= right):
                lo -= 1
                cum += hist[lo]
            elif can_right:
                hi += 1
                cum += hist[hi]
            else:
                break
        val = edges[lo]
        vah = edges[hi + 1]
        return poc, vah, val
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < p["profile_window"]:
            return None
        window = data.iloc[-p["profile_window"]:]
        poc, vah, val = self._calc_volume_profile(window)
        price = data["close"].iloc[-1]
        
        tr = pd.concat([
            data["high"] - data["low"],
            (data["high"] - data["close"].shift()).abs(),
            (data["low"] - data["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(p["atr_period"]).mean().iloc[-1]
        
        # 跌破 VAL 反彈 → 做多回到 POC
        if price < val and data["close"].iloc[-1] > data["close"].iloc[-2]:
            entry = price
            sl = entry - atr * 1.2
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[poc, vah],
                confidence=0.65, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale=f"價格跌破 VAL={val:.2f},均值回歸至 POC={poc:.2f}/VAH={vah:.2f}",
            )
        # 突破 VAH 回落 → 做空回到 POC
        if price > vah and data["close"].iloc[-1] < data["close"].iloc[-2]:
            entry = price
            sl = entry + atr * 1.2
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[poc, val],
                confidence=0.65, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale=f"價格突破 VAH={vah:.2f},均值回歸至 POC={poc:.2f}/VAL={val:.2f}",
            )
        return None


class AthenaProfile(BaseStrategy):
    """
    Bot #5 · Athena · 拍賣理論
    Composite Profile 多時框拍賣分析
    時框 1D/週 · 美股七巨頭
    """
    SCHOOL = "拍賣理論"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
    
    def _get_params(self) -> dict:
        return {
            "composite_days": 20,
            "single_print_threshold": 0.05,  # 單一價格成交量低於整體 5% 視為 single print
            "balance_breakout_pct": 0.015,
            "rr_ratio": 2.5,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if len(data) < p["composite_days"] * 2:
            return None
        
        window = data.iloc[-p["composite_days"]:]
        composite_high = window["high"].max()
        composite_low = window["low"].min()
        composite_range = composite_high - composite_low
        price = data["close"].iloc[-1]
        
        # Balance area 突破:價格突破 composite range 邊界
        breakout_long = price > composite_high * (1 - p["balance_breakout_pct"])
        breakout_short = price < composite_low * (1 + p["balance_breakout_pct"])
        
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        if breakout_long:
            entry = price
            sl = composite_low + composite_range * 0.3
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "AAPL"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                confidence=0.7, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale=f"Composite Profile 上緣突破 {composite_high:.2f},Balance Area 終結",
            )
        if breakout_short:
            entry = price
            sl = composite_high - composite_range * 0.3
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "AAPL"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                confidence=0.7, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale=f"Composite Profile 下緣破位 {composite_low:.2f}",
            )
        return None


class TempestOrderFlow(BaseStrategy):
    """
    Bot #6 · Tempest · 訂單流
    Footprint Delta + 主動吸收偵測
    時框 1m/Tick · BTC/ETH
    """
    SCHOOL = "訂單流"
    DEFAULT_TIMEFRAME = "1m"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "delta_window": 30,
            "delta_threshold_zscore": 2.0,
            "absorption_ratio": 0.7,  # 大量買進但價格不漲視為吸收
            "rr_ratio": 2.0,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        # data 需含 buy_volume / sell_volume 欄位 (來自 Binance trade feed 聚合)
        p = self.params
        required_cols = {"buy_volume", "sell_volume"}
        if not required_cols.issubset(data.columns) or len(data) < p["delta_window"]:
            return None
        
        delta = data["buy_volume"] - data["sell_volume"]
        cum_delta = delta.rolling(p["delta_window"]).sum()
        delta_z = (cum_delta - cum_delta.rolling(100).mean()) / (cum_delta.rolling(100).std() + 1e-9)
        latest_z = delta_z.iloc[-1]
        
        price = data["close"].iloc[-1]
        price_change_pct = (price - data["close"].iloc[-p["delta_window"]]) / data["close"].iloc[-p["delta_window"]]
        
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        # 多單:強烈買盤但價格未漲 → 吸收完成 → 反轉上行
        if latest_z > p["delta_threshold_zscore"] and price_change_pct < 0.002:
            entry = price
            sl = data["low"].iloc[-p["delta_window"]:].min() * 0.999
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist * 0.5, entry + tp_dist],
                confidence=min(0.9, 0.5 + latest_z * 0.1),
                timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale=f"Footprint 大量主動買盤吸收完成,Delta z={latest_z:.2f}",
            )
        if latest_z < -p["delta_threshold_zscore"] and price_change_pct > -0.002:
            entry = price
            sl = data["high"].iloc[-p["delta_window"]:].max() * 1.001
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist * 0.5, entry - tp_dist],
                confidence=min(0.9, 0.5 + abs(latest_z) * 0.1),
                timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale=f"Footprint 大量主動賣盤吸收完成,Delta z={latest_z:.2f}",
            )
        return None


class RiptideCVD(BaseStrategy):
    """
    Bot #7 · Riptide · 訂單流
    CVD (Cumulative Volume Delta) 背離 + 大單追蹤
    時框 5m · 主流幣 Top 10
    """
    SCHOOL = "訂單流"
    DEFAULT_TIMEFRAME = "5m"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "cvd_lookback": 60,
            "divergence_min_bars": 10,
            "rr_ratio": 2.2,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        if "buy_volume" not in data.columns or len(data) < p["cvd_lookback"]:
            return None
        
        cvd = (data["buy_volume"] - data["sell_volume"]).cumsum()
        
        window = data.iloc[-p["cvd_lookback"]:]
        cvd_window = cvd.iloc[-p["cvd_lookback"]:]
        
        price_high_idx = window["close"].idxmax()
        price_low_idx = window["close"].idxmin()
        latest_idx = data.index[-1]
        
        # 看漲背離:價格新低但 CVD 沒新低
        if (price_low_idx == latest_idx and 
            cvd_window.iloc[-1] > cvd_window.iloc[:-p["divergence_min_bars"]].min()):
            entry = data["close"].iloc[-1]
            sl = data["low"].iloc[-p["cvd_lookback"]:].min() * 0.998
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist],
                confidence=0.62, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale="CVD 看漲背離:價格新低但累積買賣差未跟隨",
            )
        # 看跌背離
        if (price_high_idx == latest_idx and
            cvd_window.iloc[-1] < cvd_window.iloc[:-p["divergence_min_bars"]].max()):
            entry = data["close"].iloc[-1]
            sl = data["high"].iloc[-p["cvd_lookback"]:].max() * 1.002
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist],
                confidence=0.62, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(timezone.utc),
                rationale="CVD 看跌背離:價格新高但累積買賣差未跟隨",
            )
        return None
