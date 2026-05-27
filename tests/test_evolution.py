"""
進化機制單元測試
- run_cycle:正確分類前/後段班
- breed:子代結構正確,參數有變異
- sandbox_retrain:返回 (bool, dict)
- retire:連 2 週期墊底應退役
"""
import pytest
import copy
from AutoTrading.evolution.manager import EvolutionManager, EvolutionEvent
from AutoTrading.strategies.base import BotMetrics
from AutoTrading.strategies.cross.ta_quant_macro_sentiment_meta import BayesMeanRev


# ─── helpers ────────────────────────────────

def _make_metrics(bot_id: str, score: float, wr: float = 0.65) -> BotMetrics:
    return BotMetrics(
        bot_id=bot_id, win_rate=wr, sharpe=score * 3,
        max_drawdown=0.1, pnl_pct=score * 0.5,
        monthly_stability=5.0, composite_score=score,
        total_trades=50, period_days=30,
    )


def _make_bots(n: int = 10):
    """建立 n 個 BayesMeanRev 實例作為模擬 bot"""
    bots = []
    for i in range(n):
        bot = BayesMeanRev(bot_id=f"C{i:02d}", name=f"bot-{i:02d}",
                           initial_capital=300.0)
        bots.append(bot)
    return bots


@pytest.fixture
def manager():
    return EvolutionManager(
        cycle_days=30,
        bottom_pct=0.15,
        top_pct=0.10,
        consecutive_bottom_to_retire=2,
        sandbox_min_backtest_months=18,
        breed_competition_days=90,
    )


@pytest.fixture
def ten_bots():
    return _make_bots(10)


# ─── run_cycle ───────────────────────────────

def test_run_cycle_returns_events(manager, ten_bots):
    """run_cycle 應回傳 EvolutionEvent 列表"""
    metrics = {b.bot_id: _make_metrics(b.bot_id, score=(i+1)*0.1)
               for i, b in enumerate(ten_bots)}
    for b in ten_bots:
        manager.bot_status[b.bot_id] = "active"

    events = manager.run_cycle(ten_bots, metrics)
    assert isinstance(events, list)
    assert len(events) > 0


def test_top_bots_get_promote_breed(manager, ten_bots):
    """分數最高的 bot 應觸發 promote_breed (前 10%)"""
    # 10 bots,前 10% = 1 個
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    metrics = {b.bot_id: _make_metrics(b.bot_id, score=scores[i])
               for i, b in enumerate(ten_bots)}
    for b in ten_bots:
        manager.bot_status[b.bot_id] = "active"

    events = manager.run_cycle(ten_bots, metrics)
    promoted = [e for e in events if e.action == "promote_breed"]
    assert len(promoted) >= 1
    # 最高分的 bot 應在其中
    top_bot_id = ten_bots[-1].bot_id  # 分數 1.0
    assert any(e.bot_id == top_bot_id for e in promoted)


def test_bottom_bots_get_sandbox(manager, ten_bots):
    """分數最低的 bot 應觸發 demote_sandbox (後 15%)"""
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    metrics = {b.bot_id: _make_metrics(b.bot_id, score=scores[i])
               for i, b in enumerate(ten_bots)}
    for b in ten_bots:
        manager.bot_status[b.bot_id] = "active"

    events = manager.run_cycle(ten_bots, metrics)
    sandboxed = [e for e in events if e.action == "demote_sandbox"]
    assert len(sandboxed) >= 1
    bottom_bot_id = ten_bots[0].bot_id  # 分數 0.1
    assert any(e.bot_id == bottom_bot_id for e in sandboxed)


def test_consecutive_bottom_leads_to_retire(manager, ten_bots):
    """連 2 週期墊底應退役"""
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    metrics = {b.bot_id: _make_metrics(b.bot_id, score=scores[i])
               for i, b in enumerate(ten_bots)}
    for b in ten_bots:
        manager.bot_status[b.bot_id] = "active"

    # 第一週期
    manager.run_cycle(ten_bots, metrics)
    bottom_id = ten_bots[0].bot_id

    # 強制設為 sandbox (上次已是底部)
    manager.bot_status[bottom_id] = "sandbox"

    # 第二週期:再次墊底
    events2 = manager.run_cycle(ten_bots, metrics)
    retire_events = [e for e in events2 if e.action == "retire"]
    assert any(e.bot_id == bottom_id for e in retire_events), \
        "連 2 週期墊底的 bot 應被退役"
    assert manager.bot_status[bottom_id] == "retired"


def test_breed_produces_offspring(manager, ten_bots):
    """breed 應產生 2 個子代,且各有參數變異"""
    parent = ten_bots[0]
    original_params = parent.params.copy()
    children = manager.breed(parent, n_offspring=2)

    assert len(children) == 2
    for i, child in enumerate(children):
        assert child.bot_id != parent.bot_id
        assert f"子{i+1}" in child.name
        assert child.capital == 300.0
        assert child.trade_log == []
        assert child.equity_curve == [300.0]
        # 參數應有變異(至少一個參數不同)
        has_mutation = any(
            child.params[k] != original_params[k]
            for k in original_params
            if isinstance(original_params[k], (int, float))
            and not isinstance(original_params[k], bool)
        )
        assert has_mutation, f"子代 {i+1} 應有參數變異"


def test_breed_children_are_independent(manager, ten_bots):
    """子代之間應相互獨立(不共享 trade_log)"""
    parent = ten_bots[0]
    c1, c2 = manager.breed(parent, n_offspring=2)
    c1.trade_log.append({"pnl": 10})
    assert len(c2.trade_log) == 0


def test_get_active_roster(manager, ten_bots):
    """get_active_roster 應只回傳 active/breeding 狀態的 bot"""
    for b in ten_bots[:8]:
        manager.bot_status[b.bot_id] = "active"
    manager.bot_status[ten_bots[8].bot_id] = "sandbox"
    manager.bot_status[ten_bots[9].bot_id] = "retired"

    roster = manager.get_active_roster()
    assert len(roster) == 8
    assert ten_bots[8].bot_id not in roster
    assert ten_bots[9].bot_id not in roster


def test_export_events_json(manager, ten_bots):
    """export_events 應回傳合法 JSON 字串"""
    import json
    metrics = {b.bot_id: _make_metrics(b.bot_id, score=(i+1)*0.1)
               for i, b in enumerate(ten_bots)}
    for b in ten_bots:
        manager.bot_status[b.bot_id] = "active"
    manager.run_cycle(ten_bots, metrics)

    json_str = manager.export_events()
    data = json.loads(json_str)
    assert isinstance(data, list)
    assert len(data) > 0
    for ev in data:
        assert "timestamp" in ev
        assert "action" in ev
        assert "bot_name" in ev


def test_evolution_event_metrics_none_ok(manager):
    """sandbox_pass 事件的 metrics=None 不應造成 export_events 崩潰"""
    from AutoTrading.evolution.manager import EvolutionEvent
    from datetime import datetime
    manager.events.append(EvolutionEvent(
        timestamp=datetime.now(),
        bot_id="C99", bot_name="test",
        action="sandbox_pass", metrics=None,
        note="沙盒測試通過",
    ))
    import json
    data = json.loads(manager.export_events())
    assert data[-1]["composite_score"] is None
