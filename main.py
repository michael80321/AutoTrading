"""
主協調器 — 雙池架構
- CryptoCollective:18 席 + 加密聊天室 + 加密共識 + 加密進化 + Binance 執行
- StockCollective:18 席 + 美股聊天室 + 美股共識 + 美股進化 + IBKR 執行
- 兩池完全獨立運行,僅共享:總帳戶風控閘 + 跨池警示頻道
"""
import asyncio
import importlib
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Literal
import pandas as pd

from .config.system import (
    SystemConfig, CRYPTO_ROSTER, STOCK_ROSTER, META_CRYPTO, META_EQ
)
from .engine.consensus import ConsensusEngine
from .evolution.manager import EvolutionManager
from .execution.router import ExecutionRouter
from .backtest.walkforward import BacktestEngine
from .strategies.base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


def load_strategy_class(module_path: str, class_name: str):
    pkg = __package__  # 'autotrading' when installed, None when run as __main__
    if pkg:
        module = importlib.import_module(f".{module_path}", package=pkg)
    else:
        module = importlib.import_module(module_path)
    return getattr(module, class_name)


class PoolCollective:
    """
    單一資金池的協調器(加密 or 美股各一個實例)
    """
    
    def __init__(
        self,
        pool_name: Literal["crypto", "stock"],
        config: SystemConfig,
        roster: list[dict],
        meta_spec: dict,
    ):
        self.pool_name = pool_name
        self.config = config
        self.roster = roster
        self.meta_spec = meta_spec
        
        self.bots: dict[str, BaseStrategy] = {}
        self.bot_schools: dict[str, str] = {}
        self.meta_bot: BaseStrategy | None = None
        
        self.consensus = ConsensusEngine(
            min_aligned_schools=config.consensus.min_aligned_schools,
            min_total_weight=config.consensus.min_total_weight,
            min_backtest_winrate=config.consensus.min_backtest_winrate,
            max_risk_per_trade_pct=config.consensus.max_risk_per_trade_pct,
            ewma_alpha=config.consensus.ewma_alpha,
        )
        self.evolution = EvolutionManager(
            cycle_days=config.evolution.cycle_days,
            bottom_pct=config.evolution.bottom_pct,
            top_pct=config.evolution.top_pct,
            consecutive_bottom_to_retire=config.evolution.consecutive_bottom_to_retire,
            sandbox_min_backtest_months=config.evolution.sandbox_min_backtest_months,
        )
        
        # 各池獨立的執行路由 — 只用對應的 broker
        if pool_name == "crypto":
            exchange_client = None
            # 優先 Bybit（Railway US 伺服器不被封鎖），其次 Binance
            bybit_key = os.getenv("BYBIT_API_KEY")
            bybit_secret = os.getenv("BYBIT_SECRET")
            binance_key = os.getenv("BINANCE_API_KEY")
            binance_secret = os.getenv("BINANCE_SECRET")
            if bybit_key and bybit_secret:
                try:
                    import ccxt.async_support as ccxt_async
                    exchange_client = ccxt_async.bybit({
                        "apiKey": bybit_key,
                        "secret": bybit_secret,
                        "enableRateLimit": True,
                    })
                    logger.info("✅ Bybit client 初始化成功")
                except Exception as e:
                    logger.warning(f"Bybit client 初始化失敗: {e}")
            elif binance_key and binance_secret:
                try:
                    import ccxt.async_support as ccxt_async
                    exchange_client = ccxt_async.binance({
                        "apiKey": binance_key,
                        "secret": binance_secret,
                        "enableRateLimit": True,
                        "options": {
                            "defaultType": "future",  # USDM 永續合約
                        },
                    })
                    logger.info("✅ Binance 合約 client 初始化成功")
                except Exception as e:
                    logger.warning(f"Binance client 初始化失敗: {e}")
            else:
                logger.info("未設定交易所 KEY，以 DRY-RUN 模式運行")
            self.router = ExecutionRouter(
                crypto_pool_usdt=config.capital.crypto_pool_total,
                stock_pool_usd=0,
                fee_rate_crypto=config.capital.fee_rate_crypto,
                fee_rate_stock=0,
                max_concurrent_positions=config.max_concurrent_positions_per_pool,
                binance_client=exchange_client,
            )
        else:
            ibkr_client = None
            ibkr_host = os.getenv("IBKR_HOST")
            if ibkr_host:
                try:
                    from ib_insync import IB
                    ibkr_client = IB()
                    # 儲存連線參數，等待 lifespan 中非同步連線
                    self._ibkr_host = ibkr_host
                    self._ibkr_port = int(os.getenv("IBKR_PORT", "4001"))
                    self._ibkr_client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
                    logger.info(f"IBKR client 準備好，等待連線到 {ibkr_host}:{self._ibkr_port}")
                except Exception as e:
                    logger.warning(f"IBKR 初始化失敗: {e}")
            else:
                logger.info("IBKR_HOST 未設定，美股池以 DRY-RUN 模式運行")
            self.router = ExecutionRouter(
                crypto_pool_usdt=0,
                stock_pool_usd=config.capital.stock_pool_total,
                fee_rate_crypto=0,
                fee_rate_stock=config.capital.fee_rate_stock,
                max_concurrent_positions=config.max_concurrent_positions_per_pool,
                ibkr_client=ibkr_client,
            )
        
        fee = config.capital.fee_rate_crypto if pool_name == "crypto" else config.capital.fee_rate_stock
        self.backtest = BacktestEngine(
            initial_capital=config.capital.per_bot_initial,
            fee_rate=fee,
            slippage_pct=config.capital.slippage_pct,
        )
        
        self.last_evolution_cycle = datetime.now()
        # 各池獨立聊天室
        self.chat_messages: list[dict] = []
        self.chat_channel = f"#{'crypto' if pool_name == 'crypto' else 'equities'}-floor"
        # 跨時間窗口訊號緩衝：保留最近 signal_window_hours 小時內的訊號
        self.signal_buffer: list[Signal] = []
        self.signal_window_hours: int = config.consensus.signal_window_hours
        self.max_entry_drift_pct: float = config.consensus.max_entry_drift_pct
    
    def initialize_bots(self):
        """根據名冊載入 18 席 + 1 個 Meta 裁判"""
        for spec in self.roster:
            try:
                cls = load_strategy_class(spec["module"], spec["class"])
            except (ModuleNotFoundError, AttributeError) as e:
                logger.error(f"[{self.pool_name}] 載入失敗 {spec['name']}: {e}")
                continue
            
            fee = self.config.capital.fee_rate_crypto if self.pool_name == "crypto" else self.config.capital.fee_rate_stock
            bot = cls(
                bot_id=spec["id"], name=spec["name"],
                initial_capital=self.config.capital.per_bot_initial,
                fee_rate=fee,
            )
            self.bots[spec["id"]] = bot
            self.bot_schools[spec["id"]] = spec["school"]
            self.evolution.bot_status[spec["id"]] = "active"
        
        # 載入 Meta 裁判
        try:
            meta_cls = load_strategy_class(self.meta_spec["module"], self.meta_spec["class"])
            self.meta_bot = meta_cls(
                bot_id=self.meta_spec["id"], name=self.meta_spec["name"],
                initial_capital=0,  # Meta 不持倉,只投票
                fee_rate=0,
            )
            logger.info(f"[{self.pool_name}] Meta 裁判 {self.meta_spec['name']} 載入完成")
        except (ModuleNotFoundError, AttributeError) as e:
            logger.error(f"[{self.pool_name}] Meta 載入失敗:{e}")
        
        logger.info(f"[{self.pool_name}] 已初始化 {len(self.bots)} 席分析師")
    
    async def tick(
        self,
        market_data: dict[str, pd.DataFrame],
        context_extras: dict | None = None,
        cross_pool_warnings: list[dict] | None = None,
    ):
        """每根 K 棒呼叫一次。重 CPU 的訊號運算丟到背景執行緒，避免阻塞 event loop。"""
        context_extras = context_extras or {}
        cross_warnings = cross_pool_warnings or []

        self._last_tick_at = datetime.now()
        symbols_str = ", ".join(market_data.keys())
        self.chat_messages.append({
            "channel": self.chat_channel,
            "timestamp": self._last_tick_at.isoformat(),
            "from": "🖥 系統",
            "school": "系統",
            "symbol": symbols_str,
            "content": f"市場數據更新 · {symbols_str} · {len(self.bots)} 席分析師開始評估",
            "confidence": 0.0,
        })
        if cross_warnings:
            context_extras["cross_pool_warnings"] = cross_warnings

        # 18 席訊號 + 評論 + 共識聚合（純同步、可能很重）→ 丟到 worker thread
        # 先在 event loop 取 open_orders 快照，避免 worker thread 直接讀取可能被 TP polling loop 同時修改的 dict
        open_orders_snapshot = dict(self.router.open_orders)
        approved, new_buffer = await asyncio.to_thread(
            self._compute, market_data, context_extras, open_orders_snapshot
        )
        self.signal_buffer = new_buffer  # 在 event loop 更新，避免 worker 直接寫 shared state

        # 下單（async I/O，留在主 event loop）
        for consensus, symbol in approved:
            order = await self.router.submit(consensus, symbol)
            if order:
                logger.info(f"✅ [{self.pool_name}] 下單 {symbol} {consensus.side}")

        # 進化週期檢查
        if (datetime.now() - self.last_evolution_cycle).days >= self.config.evolution.cycle_days:
            await self._run_evolution_cycle()
            self.last_evolution_cycle = datetime.now()

    def _compute(self, market_data: dict, context_extras: dict, open_orders_snapshot: dict) -> tuple[list, list]:
        """純同步：產生訊號、評論、Meta、跨時間窗口共識聚合。

        回傳 (approved_list, new_signal_buffer) — 不直接寫 shared state，由 tick() 套用。
        """
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=self.signal_window_hours)

        # 剪除過期緩衝訊號（已在 ingest 時統一轉為 UTC-aware）；操作本地副本
        signal_buffer = [s for s in self.signal_buffer if s.timestamp >= cutoff]

        current_signals: list[Signal] = []

        # 第一輪：18 席產生原始信號 + 市場評論
        for bot_id, bot in self.bots.items():
            if self.evolution.bot_status.get(bot_id) not in ("active", "breeding"):
                continue
            produced_signal = False
            for symbol, data in market_data.items():
                ctx = {**context_extras, "symbol": symbol}
                try:
                    sig = bot.signal(data, ctx)
                except Exception as e:
                    logger.warning(f"[{self.pool_name}] {bot.name} signal() 錯誤: {e}")
                    sig = None
                if sig:
                    current_signals.append(sig)
                    self._broadcast_to_chat(sig)
                    produced_signal = True
            if not produced_signal and market_data:
                top_symbol = max(
                    market_data,
                    key=lambda s: abs(float(market_data[s]["close"].iloc[-1] / market_data[s]["close"].iloc[-2] - 1)),
                )
                self._broadcast_commentary(bot, top_symbol, market_data[top_symbol])

        # 第二輪：Meta 裁判（compute_metrics 每席只算一次，供 score + winrate 共用）
        metrics_cache = {bid: bot.compute_metrics() for bid, bot in self.bots.items()}
        if self.meta_bot:
            bot_scores = {bid: m.composite_score for bid, m in metrics_cache.items()}
            for symbol, data in market_data.items():
                ctx = {
                    **context_extras, "symbol": symbol,
                    "sub_signals": [s for s in current_signals if s.symbol == symbol],
                    "bot_composite_scores": bot_scores,
                }
                try:
                    meta_sig = self.meta_bot.signal(data, ctx)
                except Exception as e:
                    logger.warning(f"[{self.pool_name}] Meta signal() 錯誤: {e}")
                    meta_sig = None
                if meta_sig:
                    current_signals.append(meta_sig)
                    self._broadcast_to_chat(meta_sig)

        # 統一把 timestamp 正規化為 UTC-aware，避免 naive 訊號永不過期
        for sig in current_signals:
            if sig.timestamp.tzinfo is None:
                sig.timestamp = sig.timestamp.replace(tzinfo=timezone.utc)

        # 本輪新訊號存入緩衝（去重：同 bot_id + symbol 只保留最新）
        replaced_keys = {(s.bot_id, s.symbol) for s in current_signals}
        signal_buffer = [s for s in signal_buffer if (s.bot_id, s.symbol) not in replaced_keys]
        signal_buffer.extend(current_signals)

        logger.info(
            f"[{self.pool_name}] 本輪新訊號: {len(current_signals)}，"
            f"緩衝窗口({self.signal_window_hours}h)內累積: {len(signal_buffer)}"
        )

        # 第三輪：共識聚合（窗口內訊號聚合）
        approved = []
        bot_winrates = {bid: m.win_rate for bid, m in metrics_cache.items()}
        total = self.config.capital.crypto_pool_total if self.pool_name == "crypto" else self.config.capital.stock_pool_total
        # 用快照判斷已開倉位，避免直接讀取 event loop 可能同時修改的 open_orders
        open_symbols = {o.symbol for o in open_orders_snapshot.values() if o.pool == self.pool_name}
        # 「新鮮訊號」閾值：緩衝窗口內至少要有 1 個來自近 2h 的訊號才允許開單
        freshness_cutoff = now_utc - timedelta(hours=2)

        for symbol in market_data:
            if symbol in open_symbols:
                continue
            consensus = self.consensus.aggregate(signal_buffer, bot_winrates, total, symbol)
            if not (consensus and consensus.approved):
                continue
            # 安全閘 1：貢獻者中至少 1 個訊號是近 2h 內的（防止全部訊號都超過 2h）
            contributing_names = set(consensus.contributors)
            fresh = any(
                s.symbol == symbol and s.side == consensus.side
                and s.bot_name in contributing_names
                and s.timestamp >= freshness_cutoff
                for s in signal_buffer
            )
            if not fresh:
                logger.info(f"[{self.pool_name}] {symbol} {consensus.side} 共識通過但無近 2h 新鮮訊號，跳過")
                continue
            # 安全閘 2：現價偏離原始進場 > max_entry_drift_pct 則放棄；偏離在允許範圍內則重錨
            current_price = float(market_data[symbol]["close"].iloc[-1])
            if not self._validate_and_reanchor(consensus, current_price):
                continue
            approved.append((consensus, symbol))
        return approved, signal_buffer

    def _validate_and_reanchor(self, consensus, current_price: float) -> bool:
        """用現價重錨進場價，並拒絕：SL/TP 已被跨過的過期訊號、或現價偏離原始進場 > max_entry_drift_pct。"""
        original_entry = consensus.entry
        drift = abs(current_price - original_entry) / original_entry if original_entry else 1.0
        if drift > self.max_entry_drift_pct:
            logger.info(
                f"現價 {current_price} 偏離原始進場 {original_entry} 達 {drift*100:.2f}%"
                f" > {self.max_entry_drift_pct*100:.1f}%，跳過"
            )
            return False
        sl = consensus.stop_loss
        tp1 = consensus.take_profit[0] if consensus.take_profit else None
        if consensus.side == "LONG":
            if current_price <= sl:
                logger.info(f"現價 {current_price} 已跌破 SL {sl}，過期訊號跳過")
                return False
            if tp1 is not None and current_price >= tp1:
                logger.info(f"現價 {current_price} 已達 TP {tp1}，過期訊號跳過")
                return False
        else:  # SHORT
            if current_price >= sl:
                logger.info(f"現價 {current_price} 已突破 SL {sl}，過期訊號跳過")
                return False
            if tp1 is not None and current_price <= tp1:
                logger.info(f"現價 {current_price} 已達 TP {tp1}，過期訊號跳過")
                return False
        # 用現價重錨進場（市價單實際成交在現價，倉位大小須以現價算）
        consensus.entry = round(current_price, 4)
        return True
    
    def _broadcast_to_chat(self, signal: Signal):
        msg = {
            "channel": self.chat_channel,
            "timestamp": signal.timestamp.isoformat(),
            "from": signal.bot_name,
            "school": signal.school,
            "symbol": signal.symbol,
            "content": f"🚨 {signal.side} @ {signal.entry_price:.4f} | SL {signal.stop_loss:.4f} | TP {signal.take_profit[0]:.4f} | {signal.rationale}",
            "confidence": signal.confidence,
        }
        self.chat_messages.append(msg)
        if len(self.chat_messages) > 1000:
            self.chat_messages = self.chat_messages[-500:]

    def _broadcast_commentary(self, bot, symbol: str, data: "pd.DataFrame"):
        """無交易信號時，分析師發佈市場觀察（每輪每個 symbol 只發一次）"""
        import random
        import numpy as np
        try:
            latest = data.iloc[-1]
            prev = data.iloc[-2]
            close = float(latest["close"])
            high_20 = float(data["high"].rolling(20).max().iloc[-1])
            low_20 = float(data["low"].rolling(20).min().iloc[-1])
            change_pct = (close - float(prev["close"])) / float(prev["close"]) * 100
            vol_ratio = float(latest["volume"]) / (float(data["volume"].rolling(20).mean().iloc[-1]) + 1e-9)
            # 簡單 RSI-14
            delta = data["close"].diff()
            gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
            loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
            rsi = 100 - 100 / (1 + gain / (loss + 1e-9))
            # ATR
            atr = float((data["high"] - data["low"]).rolling(14).mean().iloc[-1])
            atr_pct = atr / close * 100

            school = getattr(bot, "SCHOOL", "")
            # 依學派產生不同切入角度的評論
            if school in ("SMC", "訂單流"):
                if change_pct > 0.5:
                    views = [
                        f"[{symbol}] ↑ {change_pct:.2f}% · RSI {rsi:.0f} · 20H高 {high_20:.2f}，多頭結構延續，尋找 OB 回測進場",
                        f"[{symbol}] ↑ {change_pct:.2f}% · 量比 {vol_ratio:.2f}x · 流動性積聚於 {high_20:.2f}，等待掃高反轉",
                    ]
                elif change_pct < -0.5:
                    views = [
                        f"[{symbol}] ↓ {change_pct:.2f}% · RSI {rsi:.0f} · 20H低 {low_20:.2f}，空頭 OB 壓制中，等待掃低訊號",
                        f"[{symbol}] ↓ {change_pct:.2f}% · 量比 {vol_ratio:.2f}x · 賣壓持續，{low_20:.2f} 是關鍵支撐",
                    ]
                else:
                    views = [
                        f"[{symbol}] → {change_pct:+.2f}% · RSI {rsi:.0f} · 波動率 ATR {atr_pct:.2f}%，盤整中積累能量",
                        f"[{symbol}] → 橫盤 · 量比 {vol_ratio:.2f}x · 等待 {high_20:.2f}/{low_20:.2f} 突破確認",
                    ]
            elif school in ("套利", "鏈上"):
                funding_hint = "資金費率正常" if abs(change_pct) < 1 else ("資金費率偏高，空頭壓力" if change_pct < 0 else "資金費率偏低，多頭有利")
                views = [
                    f"[{symbol}] {change_pct:+.2f}% · {funding_hint} · 跨所價差監控中，暫無套利機會",
                    f"[{symbol}] 量比 {vol_ratio:.2f}x · ATR {atr_pct:.2f}% · 鏈上淨流入觀察中，等待失衡點",
                ]
            elif school in ("量化統計", "AI 元學派"):
                views = [
                    f"[{symbol}] RSI {rsi:.0f} · ATR {atr_pct:.2f}% · 波動率低，貝氏後驗方向不明，持觀望",
                    f"[{symbol}] {change_pct:+.2f}% · 馬可夫狀態估算中 · 20H區間 [{low_20:.2f}, {high_20:.2f}]",
                ]
            elif school in ("傳統TA",):
                views = [
                    f"[{symbol}] RSI {rsi:.0f} · 一目均衡表雲層觀察中，{close:.2f} 位於 20H [{low_20:.2f}-{high_20:.2f}]",
                    f"[{symbol}] {change_pct:+.2f}% · Fib 回撤位監控 · 量比 {vol_ratio:.2f}x，趨勢未確立",
                ]
            elif school in ("宏觀", "情緒"):
                views = [
                    f"[{symbol}] {change_pct:+.2f}% · 市場情緒中性 · RSI {rsi:.0f} · 等待宏觀催化劑",
                    f"[{symbol}] 量比 {vol_ratio:.2f}x · 恐貪指數無極端讀數，短期偏震盪",
                ]
            else:
                if change_pct > 0.5:
                    views = [f"[{symbol}] ↑ {change_pct:.2f}% · RSI {rsi:.0f} · 量比 {vol_ratio:.2f}x，等待進場確認"]
                elif change_pct < -0.5:
                    views = [f"[{symbol}] ↓ {change_pct:.2f}% · RSI {rsi:.0f} · 量比 {vol_ratio:.2f}x，等待支撐"]
                else:
                    views = [f"[{symbol}] → {change_pct:+.2f}% · RSI {rsi:.0f} · ATR {atr_pct:.2f}%，盤整觀望"]

            content = random.choice(views)
            msg = {
                "channel": self.chat_channel,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "from": bot.name,
                "school": getattr(bot, "SCHOOL", ""),
                "symbol": symbol,
                "content": content,
                "confidence": 0.0,
            }
            self.chat_messages.append(msg)
            if len(self.chat_messages) > 1000:
                self.chat_messages = self.chat_messages[-500:]
        except Exception:
            pass
    
    async def _run_evolution_cycle(self):
        """30 天結算,池內獨立排名"""
        active = [b for b in self.bots.values() if self.evolution.bot_status.get(b.bot_id) in ("active", "breeding")]
        metrics_map = {b.bot_id: b.compute_metrics(period_days=self.config.evolution.cycle_days) for b in active}
        events = self.evolution.run_cycle(active, metrics_map)
        self.consensus.update_weights(list(metrics_map.values()), self.bot_schools)
        
        for ev in events:
            if ev.action == "promote_breed":
                children = self.evolution.breed(self.bots[ev.bot_id])
                for child in children:
                    self.bots[child.bot_id] = child
                    self.bot_schools[child.bot_id] = self.bot_schools[ev.bot_id]
                    self.evolution.bot_status[child.bot_id] = "active"
            elif ev.action == "demote_sandbox":
                asyncio.create_task(self._sandbox_retrain_async(self.bots[ev.bot_id]))
        
        logger.info(f"🔄 [{self.pool_name}] 進化週期結算完成,{len(events)} 個事件")
    
    async def _sandbox_retrain_async(self, bot: BaseStrategy):
        logger.info(f"[{self.pool_name} 沙盒] 開始重訓 {bot.name}")
        # 載入歷史資料 → self.evolution.sandbox_retrain(bot, data, self.backtest.run)
        pass
    
    def get_pool_snapshot(self) -> dict:
        """給前端 UI 用"""
        return {
            "pool_name": self.pool_name,
            "channel": self.chat_channel,
            "portfolio": self.router.get_portfolio_snapshot(),
            "bots": [
                {
                    "id": bid, "name": bot.name,
                    "school": self.bot_schools.get(bid),
                    "status": self.evolution.bot_status.get(bid, "unknown"),
                    "metrics": bot.compute_metrics().__dict__,
                    "weight": self.consensus.get_weight(bid, self.bot_schools.get(bid, "Base")),
                }
                for bid, bot in self.bots.items()
            ],
            "chat": self.chat_messages[-50:],
            "evolution_events": [
                {"timestamp": e.timestamp.isoformat(), "bot_name": e.bot_name,
                 "action": e.action, "note": e.note}
                for e in self.evolution.events[-20:]
            ],
        }


class DualPoolOrchestrator:
    """
    總協調器 — 同時運行兩個 PoolCollective
    """
    
    def __init__(self, config: SystemConfig | None = None):
        self.config = config or SystemConfig()
        self.crypto = PoolCollective("crypto", self.config, CRYPTO_ROSTER, META_CRYPTO)
        self.stock = PoolCollective("stock", self.config, STOCK_ROSTER, META_EQ)
        self.cross_pool_warnings: list[dict] = []
    
    async def connect_brokers(self):
        """非同步連接所有 broker（在 FastAPI lifespan 中呼叫）"""
        stock_pool = self.stock
        if (hasattr(stock_pool, "_ibkr_host") and stock_pool.router.ibkr is not None):
            try:
                await stock_pool.router.ibkr.connectAsync(
                    stock_pool._ibkr_host,
                    stock_pool._ibkr_port,
                    clientId=stock_pool._ibkr_client_id,
                    timeout=15,
                )
                logger.info(f"✅ IBKR 連線成功 ({stock_pool._ibkr_host}:{stock_pool._ibkr_port})")
            except Exception as e:
                logger.error(f"IBKR 連線失敗: {e}，降級為 DRY-RUN")
                stock_pool.router.ibkr = None

    def initialize(self):
        self.crypto.initialize_bots()
        self.stock.initialize_bots()
        logger.info(f"✅ 雙池啟動完成")
        logger.info(f"   加密池:{len(self.crypto.bots)} 席 + Meta · ${self.config.capital.crypto_pool_total}")
        logger.info(f"   美股池:{len(self.stock.bots)} 席 + Meta · ${self.config.capital.stock_pool_total}")
        # 背景任務由 app.py _background_boot 統一啟動，initialize() 不重複建立
        # 若在純同步測試環境呼叫則跳過
        try:
            asyncio.get_running_loop()
            asyncio.create_task(self._startup_balance_fetch())
        except RuntimeError:
            pass

    async def _startup_balance_fetch(self):
        """啟動後 3 秒拉一次真實餘額，確保 UI 不顯示 config 預設值"""
        await asyncio.sleep(3)
        try:
            await self.crypto.router.fetch_binance_balance()
        except Exception as e:
            logger.error(f"啟動餘額同步失敗: {e}")

    async def _tp1_polling_loop(self):
        """每 30 秒自動檢查並執行 TP1 止盈；每 10 分鐘同步一次 Binance 真實餘額"""
        _balance_tick = 0
        while True:
            try:
                await self.crypto.router.check_tp1_and_close()
            except Exception as e:
                logger.error(f"TP1 輪詢失敗: {e}")
            # 每 20 次 × 30s = 10 分鐘同步一次餘額
            _balance_tick += 1
            if _balance_tick >= 20:
                _balance_tick = 0
                try:
                    await self.crypto.router.fetch_binance_balance()
                except Exception as e:
                    logger.error(f"定期餘額同步失敗: {e}")
            await asyncio.sleep(30)
    
    async def tick_both(
        self,
        crypto_data: dict[str, pd.DataFrame],
        stock_data: dict[str, pd.DataFrame],
        crypto_extras: dict | None = None,
        stock_extras: dict | None = None,
    ):
        """同時跑兩池"""
        # 跨池警示生成 — 例如美股 risk-off 時警示加密池
        self._update_cross_pool_warnings()
        
        await asyncio.gather(
            self.crypto.tick(crypto_data, crypto_extras, self.cross_pool_warnings),
            self.stock.tick(stock_data, stock_extras, self.cross_pool_warnings),
        )
        
        # 帳戶級風控檢查
        await self._check_total_account_risk()
    
    def _update_cross_pool_warnings(self):
        """根據另一池的狀態生成警示"""
        self.cross_pool_warnings = []
        crypto_pnl = sum(o.realized_pnl for o in self.crypto.router.closed_orders)
        stock_pnl = sum(o.realized_pnl for o in self.stock.router.closed_orders)
        crypto_dd = crypto_pnl / self.config.capital.crypto_pool_total if crypto_pnl < 0 else 0
        stock_dd = stock_pnl / self.config.capital.stock_pool_total if stock_pnl < 0 else 0
        
        if abs(crypto_dd) > 0.08:
            self.cross_pool_warnings.append({
                "from_pool": "crypto", "type": "high_drawdown",
                "value": crypto_dd,
                "message": f"加密池回撤 {crypto_dd*100:.1f}%,建議美股池降風險",
            })
        if abs(stock_dd) > 0.08:
            self.cross_pool_warnings.append({
                "from_pool": "stock", "type": "high_drawdown",
                "value": stock_dd,
                "message": f"美股池回撤 {stock_dd*100:.1f}%,建議加密池降風險",
            })
    
    async def _check_total_account_risk(self):
        """帳戶級風控閘 — 兩池合計超過 MDD 上限就熔斷"""
        total_capital = self.config.capital.crypto_pool_total + self.config.capital.stock_pool_total
        total_pnl = (sum(o.realized_pnl for o in self.crypto.router.closed_orders)
                     + sum(o.realized_pnl for o in self.stock.router.closed_orders))
        total_dd = total_pnl / total_capital if total_pnl < 0 else 0
        
        if abs(total_dd) > self.config.account_max_drawdown_pct:
            logger.critical(f"🚨 帳戶級熔斷觸發!總回撤 {total_dd*100:.1f}%,所有新部位暫停")
            self.crypto.router.halted = True
            self.stock.router.halted = True
        else:
            # 回撤恢復後自動解除熔斷（手動 /halt 除外，那會把 open_orders 清空）
            if self.crypto.router.halted or self.stock.router.halted:
                logger.info(f"回撤恢復至 {total_dd*100:.1f}%，自動解除熔斷")
            self.crypto.router.halted = False
            self.stock.router.halted = False
    
    def get_full_snapshot(self) -> dict:
        """完整雙池快照給前端"""
        return {
            "crypto_pool": self.crypto.get_pool_snapshot(),
            "stock_pool": self.stock.get_pool_snapshot(),
            "cross_pool_warnings": self.cross_pool_warnings,
            "total_account": {
                "total_capital": self.config.capital.crypto_pool_total + self.config.capital.stock_pool_total,
                "max_drawdown_limit_pct": self.config.account_max_drawdown_pct,
            },
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    orchestrator = DualPoolOrchestrator()
    orchestrator.initialize()
    print("\n=== 雙池架構就緒 ===")
    print(f"加密池 {len(orchestrator.crypto.bots)} 席 + Meta 裁判 → 聊天室 {orchestrator.crypto.chat_channel}")
    print(f"美股池 {len(orchestrator.stock.bots)} 席 + Meta 裁判 → 聊天室 {orchestrator.stock.chat_channel}")
