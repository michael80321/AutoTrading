"""
Walk-forward 回測單元測試
- 最基本的跑通驗證
- BacktestResult 欄位完整性
- passed() 方法可被呼叫
- 資料不足時拋 ValueError
"""
import pytest
import pandas as pd
from AutoTrading.backtest.walkforward import BacktestEngine, BacktestResult
from AutoTrading.strategies.cross.ta_quant_macro_sentiment_meta import (
    BayesMeanRev, MacroHawk,
)
from .synthetic_data import make_mean_rev_long, make_ohlcv, ctx_risk_on


@pytest.fixture
def engine():
    return BacktestEngine(
        initial_capital=300.0,
        fee_rate=0.0004,
        slippage_pct=0.0005,
    )


@pytest.fixture
def data_300():
    return make_mean_rev_long(300)


@pytest.fixture
def data_short():
    return make_ohlcv(50)


@pytest.fixture
def bayes_bot():
    return BayesMeanRev(bot_id="C13", name="Bayes", initial_capital=300.0)


# ─── 基本跑通 ─────────────────────────────────

def test_run_completes_without_error(engine, bayes_bot, data_300):
    """BacktestEngine.run 應可完成不崩"""
    result = engine.run(bayes_bot, data_300, months=18, walk_forward_segments=6)
    assert isinstance(result, BacktestResult)


def test_result_fields_complete(engine, bayes_bot, data_300):
    """BacktestResult 應包含所有必要欄位"""
    r = engine.run(bayes_bot, data_300)
    assert r.bot_id == "C13"
    assert r.bot_name == "Bayes"
    assert isinstance(r.total_trades, int)
    assert isinstance(r.win_rate, float)
    assert 0.0 <= r.win_rate <= 1.0
    assert isinstance(r.sharpe, float)
    assert isinstance(r.max_drawdown, float)
    assert r.max_drawdown >= 0.0
    assert isinstance(r.final_equity, float)
    assert r.final_equity > 0
    assert isinstance(r.positive_expectancy, bool)
    assert isinstance(r.out_of_sample_consistency, float)
    assert 0.0 <= r.out_of_sample_consistency <= 1.0
    assert r.walk_forward_segments == 6


def test_passed_method_callable(engine, bayes_bot, data_300):
    """BacktestResult.passed() 應可被呼叫且返回 bool"""
    r = engine.run(bayes_bot, data_300)
    result = r.passed(min_winrate=0.55, min_sharpe=1.0)
    assert isinstance(result, bool)


def test_insufficient_data_raises(engine, bayes_bot, data_short):
    """資料 < 200 根應拋 ValueError"""
    with pytest.raises(ValueError, match="資料不足"):
        engine.run(bayes_bot, data_short)


def test_no_signals_returns_zero_trades(engine, data_300):
    """若策略從不發出信號,total_trades 應為 0"""
    # MacroHawk 需要 macro_data context,在 backtest 的 signal() 呼叫中無法提供
    # → 永遠不發信號 → total_trades = 0
    hawk = MacroHawk(bot_id="C15", name="Hawk", initial_capital=300.0)
    r = engine.run(hawk, data_300)
    assert r.total_trades == 0
    assert r.positive_expectancy is False


def test_result_consistency_across_runs(engine, data_300):
    """相同輸入應產生相同結果(確定性)"""
    bot1 = BayesMeanRev(bot_id="C13", name="b1", initial_capital=300.0)
    bot2 = BayesMeanRev(bot_id="C13", name="b2", initial_capital=300.0)
    r1 = engine.run(bot1, data_300)
    r2 = engine.run(bot2, data_300)
    assert r1.total_trades == r2.total_trades
    assert r1.win_rate == r2.win_rate
    assert r1.sharpe == r2.sharpe


def test_win_rate_matches_trade_counts(engine, bayes_bot, data_300):
    """win_rate 應與 winning_trades/total_trades 一致"""
    r = engine.run(bayes_bot, data_300)
    if r.total_trades > 0:
        expected = round(r.winning_trades / r.total_trades, 4)
        assert abs(r.win_rate - expected) < 1e-3


def test_expectancy_sign_matches_positive_expectancy(engine, bayes_bot, data_300):
    """expectancy > 0 當且僅當 positive_expectancy=True"""
    r = engine.run(bayes_bot, data_300)
    if r.total_trades > 0:
        assert (r.expectancy > 0) == r.positive_expectancy
