"""
鏈上學派 (On-Chain) 與套利學派 (Arbitrage)
鏈上 2 席:Glassmind (交易所流量+巨鯨)、Mempool (MEV+Gas)
套利 2 席:Arbiter (Funding Rate)、Triad (跨所/三角)
"""
from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime
from ..base import BaseStrategy, Signal


class GlassmindOnChain(BaseStrategy):
    """
    Bot #8 · Glassmind · 鏈上
    交易所流入流出 + 巨鯨地址動向
    時框 1H/1D · BTC/ETH/穩定幣
    資料來源:Glassnode / CryptoQuant / 自建 indexer
    """
    SCHOOL = "鏈上"
    DEFAULT_TIMEFRAME = "1H"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "exchange_flow_zscore": 2.0,
            "whale_threshold_btc": 1000,  # >1000 BTC 視為巨鯨
            "stablecoin_inflow_threshold": 1.5,
            "rr_ratio": 2.0,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        """
        data 需含:exchange_inflow, exchange_outflow, whale_tx_count, stablecoin_inflow
        這些欄位由 chain indexer 注入
        """
        p = self.params
        required = {"exchange_inflow", "exchange_outflow", "whale_tx_count"}
        if not required.issubset(data.columns) or len(data) < 100:
            return None
        
        net_flow = data["exchange_outflow"] - data["exchange_inflow"]  # 正=資金離開交易所(看漲)
        flow_mean = net_flow.rolling(50).mean()
        flow_std = net_flow.rolling(50).std()
        flow_z = (net_flow - flow_mean) / (flow_std + 1e-9)
        
        whale_z = (data["whale_tx_count"] - data["whale_tx_count"].rolling(50).mean()) / (data["whale_tx_count"].rolling(50).std() + 1e-9)
        
        latest_flow_z = flow_z.iloc[-1]
        latest_whale_z = whale_z.iloc[-1]
        price = data["close"].iloc[-1]
        atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
        
        # 看漲:大量資金流出交易所 + 巨鯨活躍 (累積)
        if latest_flow_z > p["exchange_flow_zscore"] and latest_whale_z > 1.0:
            entry = price
            sl = price - atr * 2.5
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist],
                confidence=0.65, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"鏈上淨流出 z={latest_flow_z:.2f},巨鯨活躍 z={latest_whale_z:.2f}",
            )
        # 看跌:大量資金流入交易所
        if latest_flow_z < -p["exchange_flow_zscore"] and latest_whale_z > 1.0:
            entry = price
            sl = price + atr * 2.5
            tp_dist = (sl - entry) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[entry - tp_dist],
                confidence=0.65, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"鏈上淨流入 z={latest_flow_z:.2f},巨鯨可能拋售",
            )
        return None


class MempoolMEV(BaseStrategy):
    """
    Bot #9 · Mempool · 鏈上
    MEV bot 動態 + Gas 訊號
    時框 即時 · ETH L2
    """
    SCHOOL = "鏈上"
    DEFAULT_TIMEFRAME = "5m"
    DEFAULT_UNIVERSE = ["ETHUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "gas_spike_zscore": 2.5,
            "mev_bundle_threshold": 50,
            "rr_ratio": 1.8,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        p = self.params
        required = {"gas_price_gwei", "mev_bundle_count"}
        if not required.issubset(data.columns) or len(data) < 50:
            return None
        
        gas_z = (data["gas_price_gwei"] - data["gas_price_gwei"].rolling(50).mean()) / (data["gas_price_gwei"].rolling(50).std() + 1e-9)
        mev = data["mev_bundle_count"].iloc[-1]
        
        # Gas 暴漲 + MEV 活躍 = 鏈上需求強 = 看漲短線
        if gas_z.iloc[-1] > p["gas_spike_zscore"] and mev > p["mev_bundle_threshold"]:
            price = data["close"].iloc[-1]
            atr = (data["high"] - data["low"]).rolling(14).mean().iloc[-1]
            entry = price
            sl = price - atr * 1.5
            tp_dist = (entry - sl) * p["rr_ratio"]
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol="ETHUSDT", side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[entry + tp_dist],
                confidence=0.55, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"Gas 暴漲 z={gas_z.iloc[-1]:.2f},MEV 活躍={mev}",
            )
        return None


class ArbiterFunding(BaseStrategy):
    """
    Bot #10 · Arbiter · 套利
    Funding Rate Arbitrage — 永續貼水時做多現貨 + 空永續
    時框 8H · Binance/Bybit
    """
    SCHOOL = "套利"
    DEFAULT_TIMEFRAME = "8H"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT"]
    
    def _get_params(self) -> dict:
        return {
            "funding_extreme_threshold": 0.0005,  # 0.05% per 8H 即年化 54.75%
            "min_spread_pct": 0.001,
            "hold_periods": 3,  # 持有 3 個資金費率週期
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        """
        data 需含 funding_rate 欄位
        策略:極端負費率時做多永續(收取資金費),極端正費率時做空永續
        本策略本質為市場中性,單筆風險極低
        """
        p = self.params
        if "funding_rate" not in data.columns or len(data) < 30:
            return None
        
        fr = data["funding_rate"].iloc[-1]
        fr_avg = data["funding_rate"].rolling(30).mean().iloc[-1]
        price = data["close"].iloc[-1]
        
        # 極端正費率:多頭過熱,做空收取費率
        if fr > p["funding_extreme_threshold"] and fr > fr_avg * 3:
            entry = price
            sl = price * 1.025  # 中性策略止損寬一些
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="SHORT", entry_price=entry, stop_loss=sl,
                take_profit=[price * 0.985],
                confidence=0.85, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"資金費率極端正 {fr*100:.3f}%,做空永續收取費率",
                metadata={"hedge_required": True, "expected_funding_yield": fr * p["hold_periods"]},
            )
        if fr < -p["funding_extreme_threshold"] and fr < fr_avg * 3:
            entry = price
            sl = price * 0.975
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol=context.get("symbol", "BTCUSDT"),
                side="LONG", entry_price=entry, stop_loss=sl,
                take_profit=[price * 1.015],
                confidence=0.85, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"資金費率極端負 {fr*100:.3f}%,做多永續收取費率",
                metadata={"hedge_required": True, "expected_funding_yield": abs(fr) * p["hold_periods"]},
            )
        return None


class TriadCrossEx(BaseStrategy):
    """
    Bot #11 · Triad · 套利
    三角套利 + 跨所價差
    時框 秒級 · Binance/Bybit/OKX
    """
    SCHOOL = "套利"
    DEFAULT_TIMEFRAME = "1m"
    DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "ETHBTC"]
    
    def _get_params(self) -> dict:
        return {
            "min_profit_after_fees_pct": 0.0015,  # 0.15% 才下手
            "max_legs": 3,
            "execution_timeout_ms": 800,
        }
    
    def _generate_signal(self, data: pd.DataFrame, context: dict) -> Optional[Signal]:
        """
        context 需提供 cross_exchange_prices 或 triangular_quotes
        本策略獨立於 K 線,純報價驅動
        """
        p = self.params
        quotes = context.get("triangular_quotes")
        if not quotes:
            return None
        
        btc_usdt = quotes.get("BTCUSDT")
        eth_usdt = quotes.get("ETHUSDT")
        eth_btc = quotes.get("ETHBTC")
        if not all([btc_usdt, eth_usdt, eth_btc]):
            return None
        
        # 三角套利路徑:USDT → BTC → ETH → USDT
        path_a = (1 / btc_usdt) * (1 / eth_btc) * eth_usdt
        # 反向:USDT → ETH → BTC → USDT
        path_b = (1 / eth_usdt) * eth_btc * btc_usdt
        
        fee_total = self.fee_rate * 3  # 三筆手續費
        
        if path_a - 1 > p["min_profit_after_fees_pct"] + fee_total:
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol="BTCUSDT", side="LONG", entry_price=btc_usdt,
                stop_loss=btc_usdt * 0.999,    # 套利幾乎不需止損,僅作為執行 timeout
                take_profit=[btc_usdt * (1 + (path_a - 1) * 0.5)],
                confidence=0.95, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"三角套利 USDT→BTC→ETH→USDT 淨利 {(path_a-1)*100:.3f}%",
                metadata={"path": "USDT-BTC-ETH-USDT", "legs": 3, "expected_profit": path_a - 1},
            )
        if path_b - 1 > p["min_profit_after_fees_pct"] + fee_total:
            return Signal(
                bot_id=self.bot_id, bot_name=self.name, school=self.SCHOOL,
                symbol="ETHUSDT", side="LONG", entry_price=eth_usdt,
                stop_loss=eth_usdt * 0.999,
                take_profit=[eth_usdt * (1 + (path_b - 1) * 0.5)],
                confidence=0.95, timeframe=self.DEFAULT_TIMEFRAME,
                timestamp=datetime.now(),
                rationale=f"三角套利 USDT→ETH→BTC→USDT 淨利 {(path_b-1)*100:.3f}%",
                metadata={"path": "USDT-ETH-BTC-USDT", "legs": 3, "expected_profit": path_b - 1},
            )
        return None
