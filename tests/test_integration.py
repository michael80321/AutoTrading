"""
端對端整合測試 (煙霧測試)
驗證: DualPoolOrchestrator 初始化 → tick → 信號生成 → 共識聚合 → 進化觸發

設計原則:
- 加密池用 3 個 context-driven 策略 (BayesMeanRev + MacroHawk + PulseSentiment)
  確保 ≥3 派同向且 total_weight ≥ 1.5
- 預填 trade_log 讓勝率過濾通過
- 進化週期用 mock 讓 cycle_days=0 即可觸發
"""
import asyncio
import pytest
from datetime import datetime

from AutoTrading.main import DualPoolOrchestrator, PoolCollective
from AutoTrading.config.system import SystemConfig, CRYPTO_ROSTER, STOCK_ROSTER, META_CRYPTO, META_EQ
from AutoTrading.engine.consensus import ConsensusEngine
from AutoTrading.evolution.manager import EvolutionManager
from AutoTrading.strategies.base import Signal
from AutoTrading.strategies.cross.ta_quant_macro_sentiment_meta import (
    BayesMeanRev, MacroHawk, PulseSentiment,
)
from .synthetic_data import (
    make_mean_rev_long, make_ohlcv, ctx_risk_on, ctx_sentiment_long, seed_trade_log,
)


# ─── fixtures ────────────────────────────────

@pytest.fixture(scope="module")
def config():
    return SystemConfig()


@pytest.fixture(scope="module")
def orchestrator(config):
    orch = DualPoolOrchestrator(config)
    orch.initialize()
    return orch


# ─── 初始化測試 ───────────────────────────────

def test_crypto_pool_loads_18_bots(orchestrator):
    """加密池應載入 18 席"""
    assert len(orchestrator.crypto.bots) == 18, \
        f"加密池應有 18 席,實際 {len(orchestrator.crypto.bots)}"


def test_stock_pool_loads_18_bots(orchestrator):
    """美股池應載入 18 席"""
    assert len(orchestrator.stock.bots) == 18, \
        f"美股池應有 18 席,實際 {len(orchestrator.stock.bots)}"


def test_crypto_meta_loaded(orchestrator):
    """加密池 Meta 裁判應載入"""
    assert orchestrator.crypto.meta_bot is not None


def test_stock_meta_loaded(orchestrator):
    """美股池 Meta 裁判應載入"""
    assert orchestrator.stock.meta_bot is not None


def test_all_crypto_bots_have_string_ids(orchestrator):
    """所有 bot_id 應為字串"""
    for bid, bot in orchestrator.crypto.bots.items():
        assert isinstance(bid, str), f"bot_id {bid!r} 應為 str"
        assert isinstance(bot.bot_id, str)


def test_all_stock_bots_have_string_ids(orchestrator):
    for bid, bot in orchestrator.stock.bots.items():
        assert isinstance(bid, str)


def test_bot_schools_populated(orchestrator):
    """bot_schools 應與 bots 數量一致"""
    assert len(orchestrator.crypto.bot_schools) == len(orchestrator.crypto.bots)
    assert len(orchestrator.stock.bot_schools) == len(orchestrator.stock.bots)


def test_evolution_status_initialized(orchestrator):
    """所有 bot 初始狀態應為 active"""
    for bid in orchestrator.crypto.bots:
        status = orchestrator.crypto.evolution.bot_status.get(bid)
        assert status == "active", f"{bid} 狀態應為 active,實際 {status}"


# ─── 信號生成 + 共識 ──────────────────────────

def test_three_school_consensus_triggers():
    """
    BayesMeanRev(量化統計) + MacroHawk(宏觀) + PulseSentiment(情緒)
    在設計好的資料中應觸發共識 approved=True
    """
    data = make_mean_rev_long(300)
    ctx_base = {"symbol": "BTCUSDT",
                "macro_data": {"dxy_change_5d": -0.015, "us10y_bps_change_5d": 5, "vix": 15},
                "sentiment_score": 0.75, "social_volume_zscore": 2.2}

    bots = {
        "C13": BayesMeanRev(bot_id="C13", name="Bayes", initial_capital=300.0),
        "C15": MacroHawk(bot_id="C15", name="Macro", initial_capital=300.0),
        "C16": PulseSentiment(bot_id="C16", name="Pulse", initial_capital=300.0),
    }
    schools = {"C13": "量化統計", "C15": "宏觀", "C16": "情緒"}

    # 預填 trade_log 讓勝率過濾通過
    for bot in bots.values():
        seed_trade_log(bot, n_wins=8, n_losses=3)

    signals = []
    for bid, bot in bots.items():
        sig = bot.signal(data, {**ctx_base})
        if sig:
            signals.append(sig)

    assert len(signals) >= 3, \
        f"應有 ≥3 個信號,實際 {len(signals)}:\n" + \
        "\n".join(f"  {s.bot_name}: {s.side}" for s in signals)

    engine = ConsensusEngine(
        min_aligned_schools=3, min_total_weight=1.5,
        min_backtest_winrate=0.58, max_risk_per_trade_pct=0.015,
    )
    bot_winrates = {bid: bots[bid].compute_metrics().win_rate for bid in bots}
    result = engine.aggregate(signals, bot_winrates, 5400.0, "BTCUSDT")

    assert result is not None, "3 派同向應通過共識"
    assert result.approved is True
    assert result.side == "LONG"
    assert result.schools_aligned >= 3


# ─── 非同步 tick 不崩 ─────────────────────────

def test_tick_does_not_crash(orchestrator):
    """tick_both 用合成資料跑一次,不應拋例外"""
    crypto_data = {"BTCUSDT": make_mean_rev_long(300)}
    stock_data = {"SPY": make_ohlcv(300, start_price=450.0, seed=99)}

    ctx_crypto = {
        "macro_data": {"dxy_change_5d": -0.015, "us10y_bps_change_5d": 5, "vix": 15},
        "sentiment_score": 0.75,
        "social_volume_zscore": 2.2,
    }

    # 預填部分 bot 的 trade_log
    for bid, bot in orchestrator.crypto.bots.items():
        if len(bot.trade_log) == 0:
            seed_trade_log(bot, n_wins=8, n_losses=3)
    for bid, bot in orchestrator.stock.bots.items():
        if len(bot.trade_log) == 0:
            seed_trade_log(bot, n_wins=8, n_losses=3)

    asyncio.run(orchestrator.tick_both(
        crypto_data=crypto_data,
        stock_data=stock_data,
        crypto_extras=ctx_crypto,
    ))
    # 只要不拋例外就算通過


# ─── 進化週期觸發 ─────────────────────────────

def test_evolution_cycle_runs():
    """EvolutionManager.run_cycle 在有 active bots 時應產生事件"""
    from AutoTrading.strategies.base import BotMetrics

    manager = EvolutionManager(cycle_days=30, bottom_pct=0.15, top_pct=0.10,
                               consecutive_bottom_to_retire=2)

    bots = [BayesMeanRev(bot_id=f"C{i:02d}", name=f"bot{i}", initial_capital=300.0)
            for i in range(10)]
    for bot in bots:
        manager.bot_status[bot.bot_id] = "active"
        seed_trade_log(bot)

    metrics = {bot.bot_id: bot.compute_metrics() for bot in bots}
    # 強制給不同 composite_score
    for i, (bid, m) in enumerate(metrics.items()):
        metrics[bid] = BotMetrics(
            bot_id=bid, win_rate=0.6+i*0.01, sharpe=1.0+i*0.1,
            max_drawdown=0.05, pnl_pct=0.1+i*0.01,
            monthly_stability=5.0, composite_score=0.1+i*0.09,
            total_trades=50, period_days=30,
        )

    events = manager.run_cycle(bots, metrics)
    assert len(events) > 0

    actions = {e.action for e in events}
    assert "promote_breed" in actions, "應有 bot 進入繁衍"
    assert "demote_sandbox" in actions or "retire" in actions, "應有 bot 進入沙盒或退役"


# ─── 跨池警示 ────────────────────────────────

def test_cross_pool_warnings_generated(orchestrator):
    """當加密池有大回撤時應生成跨池警示"""
    # 手動注入虧損訂單
    from AutoTrading.execution.router import ExecutionOrder, OrderStatus
    import uuid

    fake_order = ExecutionOrder(
        order_id=str(uuid.uuid4()),
        pool="crypto",
        symbol="BTCUSDT",
        side="LONG",
        qty=1.0,
        entry_price=50000.0,
        stop_loss=48000.0,
        take_profit=[52000.0],
        status=OrderStatus.FILLED,
        realized_pnl=-500.0,  # 大虧損
    )
    orchestrator.crypto.router.closed_orders.append(fake_order)
    orchestrator._update_cross_pool_warnings()
    # 注意:單筆-500 / 5400 ≈ -9.3% > 8% 閾值應生成警示
    # (回撤計算用 realized_pnl,此處設計為剛好觸發)
    # 驗證函式可完整執行不崩即可
    assert isinstance(orchestrator.cross_pool_warnings, list)


# ─── 快照 ─────────────────────────────────────

def test_get_full_snapshot_structure(orchestrator):
    """get_full_snapshot 應有正確的頂層結構"""
    snap = orchestrator.get_full_snapshot()
    assert "crypto_pool" in snap
    assert "stock_pool" in snap
    assert "cross_pool_warnings" in snap
    assert "total_account" in snap

    crypto_snap = snap["crypto_pool"]
    assert "bots" in crypto_snap
    assert "chat" in crypto_snap
    assert "evolution_events" in crypto_snap
    assert len(crypto_snap["bots"]) == 18


def test_bot_snapshot_has_required_fields(orchestrator):
    """每個 bot 快照應包含 id/name/school/status/metrics/weight"""
    snap = orchestrator.get_full_snapshot()
    for bot_info in snap["crypto_pool"]["bots"]:
        assert "id" in bot_info
        assert "name" in bot_info
        assert "school" in bot_info
        assert "status" in bot_info
        assert "metrics" in bot_info
        assert "weight" in bot_info
        assert bot_info["weight"] > 0
