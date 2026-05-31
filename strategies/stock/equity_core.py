"""
美股池的另外 15 席 — 部分重用加密池的學派類別(換 universe 與參數)
+ 新增美股版的配對交易套利、宏觀加強版

學派分布回顧:
- 拍賣理論 ×3: Volterra-EQ, Athena-EQ, Auction-Composite
- 量化統計 ×3: Bayes-EQ, Markov-EQ, StatArbPairs
- SMC ×2: SMC-Equity-Alpha, SMC-Equity-Beta
- 傳統 TA ×2: Ichimoku-EQ, Fibonacci-EQ
- 宏觀 ×2: Macro-FedWatch, Macro-Yield
- 訂單流 ×1: Level2-Tape
- 套利 ×1: PairsTrader
- 情緒 ×1: Pulse-Equity
- + 3 個專屬 (財報、期權、輪動) 在 equity_specific.py
- + 1 個 Meta-EQ Ensemble
"""
from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime
from ..base import BaseStrategy, Signal


# ============================================================
# 拍賣理論 ×3
# ============================================================
class VolterraEQ(BaseStrategy):
    """美股 #1 · 拍賣理論 · ES/NQ 期指主導"""
    SCHOOL = "拍賣理論"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "ES1!", "NQ1!"]
    
    def _get_params(self):
        return {"profile_window": 78, "value_area_pct": 0.70, "rr_ratio": 1.8, "atr_period": 14}
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < p["profile_window"]:
            return None
        window = data.iloc[-p["profile_window"]:]
        prices = window["close"].values
        vols = window["volume"].values
        hist, edges = np.histogram(prices, bins=40, weights=vols)
        poc_idx = hist.argmax()
        poc = (edges[poc_idx] + edges[poc_idx+1]) / 2
        total = hist.sum()
        target = total * p["value_area_pct"]
        cum, lo, hi = hist[poc_idx], poc_idx, poc_idx
        while cum < target and (lo > 0 or hi < len(hist) - 1):
            can_left = lo > 0
            can_right = hi < len(hist) - 1
            left = hist[lo - 1] if can_left else -np.inf
            right = hist[hi + 1] if can_right else -np.inf
            if can_left and (not can_right or left >= right):
                lo -= 1; cum += hist[lo]
            elif can_right:
                hi += 1; cum += hist[hi]
            else:
                break
        val, vah = edges[lo], edges[hi+1]
        price = data["close"].iloc[-1]
        atr = (data["high"]-data["low"]).rolling(14).mean().iloc[-1]
        if price < val and data["close"].iloc[-1] > data["close"].iloc[-2]:
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, price-atr*1.2, [poc, vah], 0.66, self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"美股拍賣:跌破 VAL={val:.2f} 回歸 POC={poc:.2f}")
        if price > vah and data["close"].iloc[-1] < data["close"].iloc[-2]:
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, price+atr*1.2, [poc, val], 0.66, self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"美股拍賣:突破 VAH={vah:.2f} 回歸 POC={poc:.2f}")
        return None


class AthenaEQ(BaseStrategy):
    """美股 #2 · 拍賣理論 · 七巨頭 Composite Profile"""
    SCHOOL = "拍賣理論"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
    
    def _get_params(self):
        return {"composite_days": 20, "breakout_pct": 0.015, "rr_ratio": 2.5}
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < p["composite_days"] * 2:
            return None
        window = data.iloc[-p["composite_days"]:]
        c_high, c_low = window["high"].max(), window["low"].min()
        c_range = c_high - c_low
        price = data["close"].iloc[-1]
        if price > c_high * (1 - p["breakout_pct"]):
            sl = c_low + c_range * 0.3
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","AAPL"),
                          "LONG", price, sl, [price+tp_dist*0.5, price+tp_dist], 0.7,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"Composite 突破 {c_high:.2f},Balance Area 終結")
        if price < c_low * (1 + p["breakout_pct"]):
            sl = c_high - c_range * 0.3
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","AAPL"),
                          "SHORT", price, sl, [price-tp_dist*0.5, price-tp_dist], 0.7,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"Composite 破位 {c_low:.2f}")
        return None


class AuctionComposite(BaseStrategy):
    """美股 #3 · 拍賣理論 · 開盤拍賣 (Open Drive vs Open Rejection)"""
    SCHOOL = "拍賣理論"
    DEFAULT_TIMEFRAME = "30m"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM"]
    
    def _get_params(self):
        return {"opening_range_minutes": 30, "drive_threshold_pct": 0.005, "rr_ratio": 2.0}
    
    def _generate_signal(self, data, context):
        # 簡化:用前 30 分鐘 K 棒判斷開盤是 Drive (強趨勢) 還是 Rejection (反轉)
        p = self.params
        if len(data) < 5:
            return None
        # 假設 data 是日內 30m K 棒,第一根為開盤
        is_first_hour = context.get("is_first_hour", False)
        if not is_first_hour:
            return None
        opening_candle = data.iloc[-1]
        body_size = abs(opening_candle["close"] - opening_candle["open"]) / opening_candle["open"]
        is_drive = body_size > p["drive_threshold_pct"]
        price = opening_candle["close"]
        atr = (data["high"]-data["low"]).rolling(14).mean().iloc[-1] if len(data) >= 14 else body_size * price
        if is_drive and opening_candle["close"] > opening_candle["open"]:
            sl = opening_candle["low"] * 0.998
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, sl, [price+tp_dist], 0.6, self.DEFAULT_TIMEFRAME,
                          datetime.now(), "Open Drive 多 — 開盤強趨勢延續")
        if is_drive and opening_candle["close"] < opening_candle["open"]:
            sl = opening_candle["high"] * 1.002
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, sl, [price-tp_dist], 0.6, self.DEFAULT_TIMEFRAME,
                          datetime.now(), "Open Drive 空")
        return None


# ============================================================
# 量化統計 ×3
# ============================================================
class BayesEQ(BaseStrategy):
    """美股 #4 · 量化統計 · Bollinger z-score 均值回歸"""
    SCHOOL = "量化統計"
    DEFAULT_TIMEFRAME = "15m"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "AAPL", "MSFT"]
    
    def _get_params(self):
        return {"bb_period": 20, "entry_zscore": 2.2, "rr_ratio": 1.5}
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < 60:
            return None
        ma = data["close"].rolling(p["bb_period"]).mean()
        std = data["close"].rolling(p["bb_period"]).std()
        z = (data["close"] - ma) / (std + 1e-9)
        latest_z = z.iloc[-1]
        price = data["close"].iloc[-1]
        momentum = abs(price - data["close"].iloc[-5]) / data["close"].iloc[-5]
        if momentum > 0.03:
            return None
        if latest_z < -p["entry_zscore"]:
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, price-std.iloc[-1]*1.5, [ma.iloc[-1]],
                          min(0.85, 0.5+abs(latest_z)*0.1), self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"z={latest_z:.2f} 極低,回歸 MA={ma.iloc[-1]:.2f}")
        if latest_z > p["entry_zscore"]:
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, price+std.iloc[-1]*1.5, [ma.iloc[-1]],
                          min(0.85, 0.5+latest_z*0.1), self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"z={latest_z:.2f} 極高,回歸 MA={ma.iloc[-1]:.2f}")
        return None


class MarkovEQ(BaseStrategy):
    """美股 #5 · 量化統計 · HMM 體制切換"""
    SCHOOL = "量化統計"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM"]
    
    def _get_params(self):
        return {"vol_window": 30, "trend_window": 50, "regime_persistence": 5, "rr_ratio": 3.0}
    
    def _detect_regime(self, data):
        p = self.params
        returns = data["close"].pct_change()
        vol = returns.rolling(p["vol_window"]).std().iloc[-1]
        trend = (data["close"].iloc[-1] - data["close"].iloc[-p["trend_window"]]) / data["close"].iloc[-p["trend_window"]]
        vol_high = returns.rolling(200).std().quantile(0.7)
        if trend > 0.04 and vol < vol_high:
            return "bull"
        if trend < -0.04 and vol < vol_high:
            return "bear"
        if vol > vol_high:
            return "high_vol"
        return "range"
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < 200:
            return None
        regime = self._detect_regime(data)
        prev = self._detect_regime(data.iloc[:-p["regime_persistence"]])
        if regime == prev:
            return None
        price = data["close"].iloc[-1]
        atr = (data["high"]-data["low"]).rolling(14).mean().iloc[-1]
        if regime == "bull":
            sl = price - atr*3
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, sl, [price+tp_dist*0.5, price+tp_dist], 0.62,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"體制 {prev}→bull")
        if regime == "bear":
            sl = price + atr*3
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, sl, [price-tp_dist*0.5, price-tp_dist], 0.62,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"體制 {prev}→bear")
        return None


class StatArbPairs(BaseStrategy):
    """美股 #6 · 量化統計 · 配對交易 (Stat Arb)"""
    SCHOOL = "量化統計"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["KO/PEP", "MA/V", "XOM/CVX", "AAPL/MSFT", "JPM/BAC"]
    
    def _get_params(self):
        return {"lookback": 60, "entry_zscore": 2.0, "exit_zscore": 0.5, "rr_ratio": 1.5}
    
    def _generate_signal(self, data, context):
        # 需要 context["paired_series"] = pd.Series 另一檔股票價格
        p = self.params
        paired = context.get("paired_series")
        if paired is None or len(data) < p["lookback"]:
            return None
        # 計算價差 z-score
        spread = data["close"] / paired
        ma = spread.rolling(p["lookback"]).mean()
        std = spread.rolling(p["lookback"]).std()
        z = (spread - ma) / (std + 1e-9)
        latest_z = z.iloc[-1]
        price = data["close"].iloc[-1]
        if latest_z < -p["entry_zscore"]:
            # 主檔便宜 → 多主檔 + 空配對
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","AAPL"),
                          "LONG", price, price*0.985, [price*ma.iloc[-1]/spread.iloc[-1]],
                          0.7, self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"配對 z={latest_z:.2f} 主檔便宜",
                          metadata={"hedge_required": True, "hedge_symbol": context.get("paired_symbol")})
        if latest_z > p["entry_zscore"]:
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","AAPL"),
                          "SHORT", price, price*1.015, [price*ma.iloc[-1]/spread.iloc[-1]],
                          0.7, self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"配對 z={latest_z:.2f} 主檔貴",
                          metadata={"hedge_required": True, "hedge_symbol": context.get("paired_symbol")})
        return None


# ============================================================
# SMC ×2
# ============================================================
class SMCEquityAlpha(BaseStrategy):
    """美股 #7 · SMC · 流動性 + OB (個股版)"""
    SCHOOL = "SMC"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["AAPL", "NVDA", "TSLA", "AMD", "META"]
    
    def _get_params(self):
        return {"swing_lookback": 20, "ob_min_body_ratio": 0.6, "rr_ratio": 2.5}
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < p["swing_lookback"]*3:
            return None
        recent = data.iloc[-p["swing_lookback"]*2:]
        latest = data.iloc[-1]
        swing_high = recent["high"].rolling(p["swing_lookback"]).max().iloc[-p["swing_lookback"]]
        swing_low = recent["low"].rolling(p["swing_lookback"]).min().iloc[-p["swing_lookback"]]
        body = abs(data["close"]-data["open"])
        rng = data["high"]-data["low"]
        body_ratio = body / (rng+1e-9)
        liq_low = data["low"].iloc[-3:-1].min() < swing_low
        liq_high = data["high"].iloc[-3:-1].max() > swing_high
        if liq_low and latest["close"] > latest["open"]:
            obs = data[(body_ratio > p["ob_min_body_ratio"]) & (data["close"] < data["open"])].iloc[-5:]
            if len(obs) > 0:
                ob = obs.iloc[-1]
                entry = latest["close"]; sl = min(ob["low"], swing_low) * 0.998
                tp_dist = (entry - sl) * p["rr_ratio"]
                return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","AAPL"),
                              "LONG", entry, sl, [entry+tp_dist*0.5, entry+tp_dist], 0.7,
                              self.DEFAULT_TIMEFRAME, datetime.now(),
                              f"美股 SMC:流動性掃過 ${swing_low:.2f} + OB")
        if liq_high and latest["close"] < latest["open"]:
            obs = data[(body_ratio > p["ob_min_body_ratio"]) & (data["close"] > data["open"])].iloc[-5:]
            if len(obs) > 0:
                ob = obs.iloc[-1]
                entry = latest["close"]; sl = max(ob["high"], swing_high) * 1.002
                tp_dist = (sl - entry) * p["rr_ratio"]
                return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","AAPL"),
                              "SHORT", entry, sl, [entry-tp_dist*0.5, entry-tp_dist], 0.7,
                              self.DEFAULT_TIMEFRAME, datetime.now(),
                              f"美股 SMC:流動性掃過 ${swing_high:.2f}")
        return None


class SMCEquityBeta(BaseStrategy):
    """美股 #8 · SMC · BOS 趨勢"""
    SCHOOL = "SMC"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN"]
    
    def _get_params(self):
        return {"bos_lookback": 30, "trend_ema": 50, "atr_period": 14, "atr_sl_mult": 1.8, "rr_ratio": 3.0}
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < p["trend_ema"] + p["bos_lookback"]:
            return None
        ema = data["close"].ewm(span=p["trend_ema"]).mean()
        trend_up = data["close"].iloc[-1] > ema.iloc[-1] and ema.iloc[-1] > ema.iloc[-10]
        trend_dn = data["close"].iloc[-1] < ema.iloc[-1] and ema.iloc[-1] < ema.iloc[-10]
        tr = pd.concat([data["high"]-data["low"],
                        (data["high"]-data["close"].shift()).abs(),
                        (data["low"]-data["close"].shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(p["atr_period"]).mean().iloc[-1]
        prev_high = data["high"].iloc[-p["bos_lookback"]:-2].max()
        prev_low = data["low"].iloc[-p["bos_lookback"]:-2].min()
        if trend_up and (data["close"].iloc[-2:] > prev_high).all():
            entry = data["close"].iloc[-1]; sl = entry - atr*p["atr_sl_mult"]
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", entry, sl, [entry+tp_dist*0.4, entry+tp_dist*0.7, entry+tp_dist],
                          0.74, self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"美股 BOS 多 — 破前高 ${prev_high:.2f}")
        if trend_dn and (data["close"].iloc[-2:] < prev_low).all():
            entry = data["close"].iloc[-1]; sl = entry + atr*p["atr_sl_mult"]
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", entry, sl, [entry-tp_dist*0.4, entry-tp_dist*0.7, entry-tp_dist],
                          0.74, self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"美股 BOS 空 — 破前低 ${prev_low:.2f}")
        return None


# ============================================================
# 傳統 TA ×2
# ============================================================
class IchimokuEQ(BaseStrategy):
    """美股 #9 · 傳統 TA · 一目均衡表"""
    SCHOOL = "傳統TA"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "AAPL", "NVDA"]
    
    def _get_params(self):
        return {"tenkan": 9, "kijun": 26, "senkou_b": 52, "displacement": 26, "rr_ratio": 2.5}
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < p["senkou_b"] + p["displacement"]:
            return None
        h, l, c = data["high"], data["low"], data["close"]
        tenkan = (h.rolling(p["tenkan"]).max() + l.rolling(p["tenkan"]).min()) / 2
        kijun = (h.rolling(p["kijun"]).max() + l.rolling(p["kijun"]).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(p["displacement"])
        senkou_b = ((h.rolling(p["senkou_b"]).max() + l.rolling(p["senkou_b"]).min()) / 2).shift(p["displacement"])
        price = c.iloc[-1]
        cloud_top = max(senkou_a.iloc[-1], senkou_b.iloc[-1])
        cloud_bot = min(senkou_a.iloc[-1], senkou_b.iloc[-1])
        bullish_cloud = senkou_a.iloc[-1] > senkou_b.iloc[-1]
        cross_up = tenkan.iloc[-1] > kijun.iloc[-1] and tenkan.iloc[-2] <= kijun.iloc[-2]
        cross_dn = tenkan.iloc[-1] < kijun.iloc[-1] and tenkan.iloc[-2] >= kijun.iloc[-2]
        if price > cloud_top and bullish_cloud and cross_up:
            sl = cloud_bot * 0.997
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, sl, [price+tp_dist*0.5, price+tp_dist], 0.68,
                          self.DEFAULT_TIMEFRAME, datetime.now(), "一目多頭三條件成立")
        if price < cloud_bot and not bullish_cloud and cross_dn:
            sl = cloud_top * 1.003
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, sl, [price-tp_dist*0.5, price-tp_dist], 0.68,
                          self.DEFAULT_TIMEFRAME, datetime.now(), "一目空頭三條件成立")
        return None


class FibonacciEQ(BaseStrategy):
    """美股 #10 · 傳統 TA · Fibonacci 回撤"""
    SCHOOL = "傳統TA"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "AAPL"]
    
    def _get_params(self):
        return {"swing_lookback": 50, "fib_levels": [0.382, 0.5, 0.618],
                "tolerance_pct": 0.005, "rr_ratio": 2.0}
    
    def _generate_signal(self, data, context):
        p = self.params
        if len(data) < p["swing_lookback"]:
            return None
        window = data.iloc[-p["swing_lookback"]:]
        sh, sl_ = window["high"].max(), window["low"].min()
        price = data["close"].iloc[-1]
        uptrend = window["high"].idxmax() > window["low"].idxmin()
        rng = sh - sl_
        if uptrend:
            for fib in p["fib_levels"]:
                level = sh - rng * fib
                if abs(price - level) / level < p["tolerance_pct"]:
                    tp_dist = (price - sl_*0.997) * p["rr_ratio"]
                    return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                                  "LONG", price, sl_*0.997, [sh, price+tp_dist],
                                  0.55+(0.1 if fib==0.618 else 0), self.DEFAULT_TIMEFRAME,
                                  datetime.now(), f"上升回撤 Fib {fib} = ${level:.2f}")
        else:
            for fib in p["fib_levels"]:
                level = sl_ + rng * fib
                if abs(price - level) / level < p["tolerance_pct"]:
                    tp_dist = (sh*1.003 - price) * p["rr_ratio"]
                    return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                                  "SHORT", price, sh*1.003, [sl_, price-tp_dist],
                                  0.55+(0.1 if fib==0.618 else 0), self.DEFAULT_TIMEFRAME,
                                  datetime.now(), f"下降反彈 Fib {fib} = ${level:.2f}")
        return None


# ============================================================
# 宏觀 ×2
# ============================================================
class MacroFedWatch(BaseStrategy):
    """美股 #11 · 宏觀 · Fed/利率/CPI 事件驅動"""
    SCHOOL = "宏觀"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "TLT"]
    
    def _get_params(self):
        return {"surprise_threshold": 0.2, "rr_ratio": 2.5}
    
    def _generate_signal(self, data, context):
        p = self.params
        # context 需要 fomc_surprise (鴿派為正), cpi_surprise (低於預期為正,股市利多)
        fomc = context.get("fomc_surprise", 0)
        cpi = context.get("cpi_surprise", 0)
        nfp = context.get("nfp_surprise", 0)
        if not any([fomc, cpi, nfp]) or len(data) < 50:
            return None
        composite = fomc * 0.5 + cpi * 0.3 + nfp * 0.2
        price = data["close"].iloc[-1]
        atr = (data["high"]-data["low"]).rolling(14).mean().iloc[-1]
        if composite > p["surprise_threshold"]:
            sl = price - atr * 2
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, sl, [price+tp_dist*0.5, price+tp_dist], 0.65,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"宏觀利多綜合分 {composite:.2f}")
        if composite < -p["surprise_threshold"]:
            sl = price + atr * 2
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, sl, [price-tp_dist*0.5, price-tp_dist], 0.65,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"宏觀利空綜合分 {composite:.2f}")
        return None


class MacroYield(BaseStrategy):
    """美股 #12 · 宏觀 · 殖利率曲線 / 信用利差"""
    SCHOOL = "宏觀"
    DEFAULT_TIMEFRAME = "1D"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "HYG", "TLT"]
    
    def _get_params(self):
        return {"yield_curve_threshold_bps": -50, "credit_spread_threshold": 5.5, "rr_ratio": 2.5}
    
    def _generate_signal(self, data, context):
        p = self.params
        curve_2s10s = context.get("yield_curve_2s10s_bps")  # 2-10 利差(負數=倒掛)
        credit_spread = context.get("hy_credit_spread_pct")  # 高收益利差
        if curve_2s10s is None or len(data) < 50:
            return None
        price = data["close"].iloc[-1]
        atr = (data["high"]-data["low"]).rolling(14).mean().iloc[-1]
        # 倒掛持續 + 利差擴大 = 風險規避訊號
        if curve_2s10s < p["yield_curve_threshold_bps"] and credit_spread and credit_spread > p["credit_spread_threshold"]:
            sl = price + atr * 2.5
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, sl, [price-tp_dist*0.5, price-tp_dist], 0.6,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"殖利率倒掛 {curve_2s10s}bps + 利差擴大 {credit_spread:.2f}%")
        return None


# ============================================================
# 訂單流 ×1
# ============================================================
class Level2Tape(BaseStrategy):
    """美股 #13 · 訂單流 · Level 2 + Time & Sales"""
    SCHOOL = "訂單流"
    DEFAULT_TIMEFRAME = "5m"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "TSLA", "NVDA"]
    
    def _get_params(self):
        return {"delta_window": 30, "delta_threshold_zscore": 2.0, "rr_ratio": 2.0}
    
    def _generate_signal(self, data, context):
        p = self.params
        if "buy_volume" not in data.columns or len(data) < p["delta_window"]:
            return None
        delta = data["buy_volume"] - data["sell_volume"]
        cum = delta.rolling(p["delta_window"]).sum()
        z = (cum - cum.rolling(100).mean()) / (cum.rolling(100).std() + 1e-9)
        latest = z.iloc[-1]
        price = data["close"].iloc[-1]
        price_chg = (price - data["close"].iloc[-p["delta_window"]]) / data["close"].iloc[-p["delta_window"]]
        if latest > p["delta_threshold_zscore"] and price_chg < 0.002:
            sl = data["low"].iloc[-p["delta_window"]:].min() * 0.998
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, sl, [price+tp_dist*0.5, price+tp_dist],
                          min(0.9, 0.5+latest*0.1), self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"美股訂單流吸收 Delta z={latest:.2f}")
        if latest < -p["delta_threshold_zscore"] and price_chg > -0.002:
            sl = data["high"].iloc[-p["delta_window"]:].max() * 1.002
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, sl, [price-tp_dist*0.5, price-tp_dist],
                          min(0.9, 0.5+abs(latest)*0.1), self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"美股訂單流壓盤 Delta z={latest:.2f}")
        return None


# ============================================================
# 套利 ×1 (ETF 套利)
# ============================================================
class ETFArbiter(BaseStrategy):
    """美股 #14 · 套利 · ETF NAV vs 市價套利"""
    SCHOOL = "套利"
    DEFAULT_TIMEFRAME = "5m"
    DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "EEM"]
    
    def _get_params(self):
        return {"nav_premium_threshold": 0.0015, "rr_ratio": 1.0}
    
    def _generate_signal(self, data, context):
        # ETF 折溢價:市價 vs intraday NAV
        p = self.params
        nav = context.get("etf_intraday_nav")
        if nav is None or len(data) < 20:
            return None
        market_price = data["close"].iloc[-1]
        premium = (market_price - nav) / nav
        if abs(premium) < p["nav_premium_threshold"]:
            return None
        if premium > p["nav_premium_threshold"]:
            # ETF 溢價 → 做空 ETF + 買入成分股 (簡化為單邊)
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", market_price, market_price*1.002, [nav*1.0005], 0.85,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"ETF 溢價 {premium*100:.3f}% — 套利做空")
        else:
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", market_price, market_price*0.998, [nav*0.9995], 0.85,
                          self.DEFAULT_TIMEFRAME, datetime.now(),
                          f"ETF 折價 {premium*100:.3f}% — 套利做多")


# ============================================================
# 情緒 ×1
# ============================================================
class PulseEquity(BaseStrategy):
    """美股 #15 · 情緒 · WSB / FinTwit / 新聞情緒"""
    SCHOOL = "情緒"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["TSLA", "NVDA", "AMC", "GME", "PLTR"]
    
    def _get_params(self):
        return {"sentiment_extreme": 0.7, "volume_z": 1.5, "contrarian_threshold": 0.85, "rr_ratio": 2.0}
    
    def _generate_signal(self, data, context):
        p = self.params
        sent = context.get("sentiment_score")
        sv = context.get("social_volume_zscore", 0)
        if sent is None or len(data) < 50:
            return None
        price = data["close"].iloc[-1]
        atr = (data["high"]-data["low"]).rolling(14).mean().iloc[-1]
        if p["sentiment_extreme"] < sent < p["contrarian_threshold"] and sv > p["volume_z"]:
            sl = price - atr*2
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","TSLA"),
                          "LONG", price, sl, [price+tp_dist], 0.55, self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"美股情緒順勢多 {sent:.2f}")
        if sent > p["contrarian_threshold"]:
            sl = price + atr*1.5
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","TSLA"),
                          "SHORT", price, sl, [price-tp_dist], 0.5, self.DEFAULT_TIMEFRAME,
                          datetime.now(), f"情緒過熱反向 {sent:.2f}")
        return None


# ============================================================
# AI 元學派 — 美股版 Meta
# ============================================================
class MetaEnsembleEQ(BaseStrategy):
    """美股 #pool meta · 融合美股池其他 17 席"""
    SCHOOL = "AI 元學派"
    DEFAULT_TIMEFRAME = "multi"
    DEFAULT_UNIVERSE = ["dynamic"]
    
    def _get_params(self):
        return {"min_subordinate_signals": 3, "diversity_bonus": 0.15, "rr_ratio": 2.2}
    
    def _generate_signal(self, data, context):
        p = self.params
        subs = context.get("sub_signals", [])
        scores = context.get("bot_composite_scores", {})
        if len(subs) < p["min_subordinate_signals"]:
            return None
        longs = [s for s in subs if s.side == "LONG"]
        shorts = [s for s in subs if s.side == "SHORT"]
        l_score = sum(scores.get(s.bot_id, 0.5) * s.confidence for s in longs)
        s_score = sum(scores.get(s.bot_id, 0.5) * s.confidence for s in shorts)
        l_sch = len({s.school for s in longs})
        s_sch = len({s.school for s in shorts})
        l_score *= (1 + p["diversity_bonus"] * (l_sch - 1))
        s_score *= (1 + p["diversity_bonus"] * (s_sch - 1))
        price = data["close"].iloc[-1]
        if l_score > s_score * 1.5 and len(longs) >= p["min_subordinate_signals"]:
            sl = max(s.stop_loss for s in longs)
            tp_dist = (price - sl) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "LONG", price, sl, [price+tp_dist*0.5, price+tp_dist],
                          min(0.95, 0.6+l_score*0.1), "multi", datetime.now(),
                          f"美股 Meta:{len(longs)} 席跨 {l_sch} 派,分 {l_score:.2f}",
                          metadata={"contributors": [s.bot_name for s in longs]})
        if s_score > l_score * 1.5 and len(shorts) >= p["min_subordinate_signals"]:
            sl = min(s.stop_loss for s in shorts)
            tp_dist = (sl - price) * p["rr_ratio"]
            return Signal(self.bot_id, self.name, self.SCHOOL, context.get("symbol","SPY"),
                          "SHORT", price, sl, [price-tp_dist*0.5, price-tp_dist],
                          min(0.95, 0.6+s_score*0.1), "multi", datetime.now(),
                          f"美股 Meta:{len(shorts)} 席跨 {s_sch} 派,分 {s_score:.2f}",
                          metadata={"contributors": [s.bot_name for s in shorts]})
        return None
