"""
共識引擎單元測試
- 動態權重更新
- 3 派同向 → approved=True
- 不足 3 派 → None
- 總加權 < min_total_weight → None
- 勝率過濾
"""
import pytest
from datetime import datetime
from AutoTrading.engine.consensus import ConsensusEngine
from AutoTrading.strategies.base import Signal, BotMetrics


# ─── helpers ────────────────────────────────

def _make_signal(bot_id: str, school: str, side: str,
                 entry: float = 50_000.0, conf: float = 0.8) -> Signal:
    sl = entry * 0.98 if side == "LONG" else entry * 1.02
    tp = [entry * 1.04] if side == "LONG" else [entry * 0.96]
    return Signal(
        bot_id=bot_id, bot_name=f"bot-{bot_id}", school=school,
        symbol="BTCUSDT", side=side,
        entry_price=entry, stop_loss=sl, take_profit=tp,
        confidence=conf, timeframe="1H",
        timestamp=datetime.now(), rationale="test",
    )


def _make_metrics(bot_id: str, score: float, wr: float = 0.65) -> BotMetrics:
    return BotMetrics(
        bot_id=bot_id, win_rate=wr, sharpe=1.5,
        max_drawdown=0.05, pnl_pct=0.1,
        monthly_stability=5.0, composite_score=score,
        total_trades=50, period_days=30,
    )


@pytest.fixture
def engine():
    return ConsensusEngine(
        min_aligned_schools=3,
        min_total_weight=1.5,
        min_backtest_winrate=0.58,
        max_risk_per_trade_pct=0.015,
        ewma_alpha=0.7,
    )


# ─── 權重更新 ────────────────────────────────

def test_update_weights_sets_dynamic(engine):
    metrics = [_make_metrics("C13", 0.7), _make_metrics("C15", 0.4)]
    schools = {"C13": "量化統計", "C15": "宏觀"}
    engine.update_weights(metrics, schools)
    assert "C13" in engine.dynamic_weights
    assert "C15" in engine.dynamic_weights
    # 高分 bot 應有更高權重
    assert engine.dynamic_weights["C13"] > engine.dynamic_weights["C15"]


def test_get_weight_fallback_to_base(engine):
    """未在 dynamic_weights 的 bot 應回退到 base_weights"""
    w = engine.get_weight("UNKNOWN", "套利")
    assert w == engine.base_weights["套利"]  # 1.2


def test_get_weight_uses_dynamic(engine):
    engine.dynamic_weights["C13"] = 1.8
    assert engine.get_weight("C13", "量化統計") == 1.8


# ─── 聚合 → approved ─────────────────────────

def test_aggregate_three_schools_long(engine):
    """3 派 LONG 同向,總加權 > 1.5,勝率過濾通過 → approved=True"""
    signals = [
        _make_signal("C13", "量化統計", "LONG", conf=0.85),
        _make_signal("C15", "宏觀",     "LONG", conf=0.70),
        _make_signal("C16", "情緒",     "LONG", conf=0.60),
    ]
    bot_winrates = {"C13": 0.65, "C15": 0.65, "C16": 0.65}
    result = engine.aggregate(signals, bot_winrates, 5400.0, "BTCUSDT")
    assert result is not None, "3 派同向應通過共識"
    assert result.approved is True
    assert result.side == "LONG"
    assert result.schools_aligned >= 3
    assert result.total_weight >= 1.5


def test_aggregate_three_schools_short(engine):
    """3 派 SHORT 同向應通過"""
    signals = [
        _make_signal("C01", "SMC",     "SHORT", conf=0.75),
        _make_signal("C10", "拍賣理論", "SHORT", conf=0.70),
        _make_signal("C13", "量化統計", "SHORT", conf=0.70),
    ]
    bot_winrates = {"C01": 0.6, "C10": 0.65, "C13": 0.62}
    result = engine.aggregate(signals, bot_winrates, 5400.0, "BTCUSDT")
    assert result is not None
    assert result.side == "SHORT"


def test_aggregate_only_two_schools_returns_none(engine):
    """只有 2 派同向 → None"""
    signals = [
        _make_signal("C13", "量化統計", "LONG", conf=0.85),
        _make_signal("C14", "量化統計", "LONG", conf=0.85),  # 同派,不算新學派
        _make_signal("C15", "宏觀",     "LONG", conf=0.70),
    ]
    bot_winrates = {"C13": 0.65, "C14": 0.65, "C15": 0.65}
    result = engine.aggregate(signals, bot_winrates, 5400.0, "BTCUSDT")
    assert result is None, "只有 2 個獨立學派不應通過共識"


def test_aggregate_insufficient_winrate(engine):
    """勝率 < 0.58 的 bot 被過濾,剩餘不足 3 席 → None"""
    signals = [
        _make_signal("C13", "量化統計", "LONG", conf=0.85),
        _make_signal("C15", "宏觀",     "LONG", conf=0.70),
        _make_signal("C16", "情緒",     "LONG", conf=0.60),
    ]
    bot_winrates = {"C13": 0.40, "C15": 0.40, "C16": 0.40}  # 全部低於 0.58
    result = engine.aggregate(signals, bot_winrates, 5400.0, "BTCUSDT")
    assert result is None


def test_aggregate_direction_conflict_returns_none(engine):
    """多空力量相近(差距 < 1.3x) → None"""
    signals = [
        _make_signal("C13", "量化統計", "LONG",  conf=0.8),
        _make_signal("C15", "宏觀",     "SHORT", conf=0.8),
        _make_signal("C16", "情緒",     "LONG",  conf=0.75),
        _make_signal("C01", "SMC",      "SHORT", conf=0.75),
    ]
    bot_winrates = {k: 0.65 for k in ["C13","C15","C16","C01"]}
    result = engine.aggregate(signals, bot_winrates, 5400.0, "BTCUSDT")
    assert result is None


def test_aggregate_wrong_symbol_ignored(engine):
    """非目標 symbol 的信號不應影響結果"""
    signals = [
        _make_signal("C13", "量化統計", "LONG", conf=0.85),
        _make_signal("C15", "宏觀",     "LONG", conf=0.70),
        _make_signal("C16", "情緒",     "LONG", conf=0.60),
    ]
    bot_winrates = {"C13": 0.65, "C15": 0.65, "C16": 0.65}
    # 查詢不同 symbol
    result = engine.aggregate(signals, bot_winrates, 5400.0, "ETHUSDT")
    assert result is None


def test_consensus_result_fields(engine):
    """ConsensusResult 欄位完整性"""
    signals = [
        _make_signal("C13", "量化統計", "LONG", conf=0.85),
        _make_signal("C15", "宏觀",     "LONG", conf=0.70),
        _make_signal("C16", "情緒",     "LONG", conf=0.60),
    ]
    bot_winrates = {"C13": 0.65, "C15": 0.65, "C16": 0.65}
    r = engine.aggregate(signals, bot_winrates, 5400.0, "BTCUSDT")
    assert r is not None
    assert r.entry > 0
    assert r.stop_loss < r.entry  # LONG 止損在進場下方
    assert len(r.take_profit) >= 1
    assert 0 < r.risk_pct <= 0.015
    assert len(r.contributors) >= 3
    assert isinstance(r.rationale, str)
