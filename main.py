"""
主協調器 — 雙池架構
- CryptoCollective:18 席 + 加密聊天室 + 加密共識 + 加密進化 + Binance 執行
- StockCollective:18 席 + 美股聊天室 + 美股共識 + 美股進化 + IBKR 執行
- 兩池完全獨立運行,僅共享:總帳戶風控閘 + 跨池警示頻道
"""
import asyncio
import importlib
import logging
from datetime import datetime
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
            self.router = ExecutionRouter(
                crypto_pool_usdt=config.capital.crypto_pool_total,
                stock_pool_usd=0,  # 此池不操作美股
                fee_rate_crypto=config.capital.fee_rate_crypto,
                fee_rate_stock=0,
                max_concurrent_positions=config.max_concurrent_positions_per_pool,
            )
        else:
            self.router = ExecutionRouter(
                crypto_pool_usdt=0,
                stock_pool_usd=config.capital.stock_pool_total,
                fee_rate_crypto=0,
                fee_rate_stock=config.capital.fee_rate_stock,
                max_concurrent_positions=config.max_concurrent_positions_per_pool,
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
        """每根 K 棒呼叫一次"""
        context_extras = context_extras or {}
        cross_warnings = cross_pool_warnings or []
        
        # 跨池警示注入到 context(只讀,不影響共識計算)
        if cross_warnings:
            context_extras["cross_pool_warnings"] = cross_warnings
        
        all_signals: list[Signal] = []
        
        # 第一輪:18 席產生原始信號
        for bot_id, bot in self.bots.items():
            if self.evolution.bot_status.get(bot_id) not in ("active", "breeding"):
                continue
            for symbol, data in market_data.items():
                ctx = {**context_extras, "symbol": symbol}
                sig = bot.signal(data, ctx)
                if sig:
                    all_signals.append(sig)
                    self._broadcast_to_chat(sig)
        
        # 第二輪:Meta 裁判看 18 席結果
        if self.meta_bot:
            bot_scores = {bid: bot.compute_metrics().composite_score for bid, bot in self.bots.items()}
            for symbol, data in market_data.items():
                ctx = {
                    **context_extras, "symbol": symbol,
                    "sub_signals": [s for s in all_signals if s.symbol == symbol],
                    "bot_composite_scores": bot_scores,
                }
                meta_sig = self.meta_bot.signal(data, ctx)
                if meta_sig:
                    all_signals.append(meta_sig)
                    self._broadcast_to_chat(meta_sig)
        
        # 第三輪:共識引擎聚合 → 執行
        bot_winrates = {bid: bot.compute_metrics().win_rate for bid, bot in self.bots.items()}
        for symbol in market_data:
            consensus = self.consensus.aggregate(
                all_signals, bot_winrates,
                self.config.capital.crypto_pool_total if self.pool_name == "crypto" else self.config.capital.stock_pool_total,
                symbol,
            )
            if consensus and consensus.approved:
                order = await self.router.submit(consensus, symbol)
                if order:
                    logger.info(f"✅ [{self.pool_name}] 下單 {symbol} {consensus.side}")
        
        # 第四輪:進化週期檢查
        if (datetime.now() - self.last_evolution_cycle).days >= self.config.evolution.cycle_days:
            await self._run_evolution_cycle()
            self.last_evolution_cycle = datetime.now()
    
    def _broadcast_to_chat(self, signal: Signal):
        msg = {
            "channel": self.chat_channel,
            "timestamp": signal.timestamp.isoformat(),
            "from": signal.bot_name,
            "school": signal.school,
            "symbol": signal.symbol,
            "content": f"{signal.side} @ {signal.entry_price:.4f} | SL {signal.stop_loss:.4f} | {signal.rationale}",
            "confidence": signal.confidence,
        }
        self.chat_messages.append(msg)
        if len(self.chat_messages) > 1000:
            self.chat_messages = self.chat_messages[-500:]
    
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
    
    def initialize(self):
        self.crypto.initialize_bots()
        self.stock.initialize_bots()
        logger.info(f"✅ 雙池啟動完成")
        logger.info(f"   加密池:{len(self.crypto.bots)} 席 + Meta · ${self.config.capital.crypto_pool_total}")
        logger.info(f"   美股池:{len(self.stock.bots)} 席 + Meta · ${self.config.capital.stock_pool_total}")
    
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
            # 實作:呼叫 router.halt_new_orders() 等等
    
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
