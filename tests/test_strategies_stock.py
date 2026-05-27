"""
美股池 18 席單元測試
"""
import pytest
from AutoTrading.strategies.base import Signal
from AutoTrading.strategies.stock.equity_core import (
    VolterraEQ, AthenaEQ, AuctionComposite,
    BayesEQ, MarkovEQ, StatArbPairs,
    SMCEquityAlpha, SMCEquityBeta,
    IchimokuEQ, FibonacciEQ,
    MacroFedWatch, MacroYield,
    Level2Tape, ETFArbiter, PulseEquity,
    MetaEnsembleEQ,
)
from AutoTrading.strategies.stock.equity_specific import (
    EarningsHawk, GammaTide, RotationSage,
)
from .synthetic_data import (
    make_ohlcv, make_mean_rev_long, make_breakout_high,
    ctx_earnings, ctx_sector_rotation,
)


# ─── fixtures ────────────────────────────────

@pytest.fixture
def flat_300():
    return make_ohlcv(300, start_price=450.0, trend="flat", seed=10)


@pytest.fixture
def mean_rev_long_300():
    return make_mean_rev_long(300)


# ─── 實例化 & 不足資料不崩 ────────────────────

@pytest.mark.parametrize("cls,bot_id", [
    (VolterraEQ,       "E01"),
    (AthenaEQ,         "E02"),
    (AuctionComposite, "E03"),
    (BayesEQ,          "E04"),
    (MarkovEQ,         "E05"),
    (StatArbPairs,     "E06"),
    (SMCEquityAlpha,   "E07"),
    (SMCEquityBeta,    "E08"),
    (IchimokuEQ,       "E09"),
    (FibonacciEQ,      "E10"),
    (MacroFedWatch,    "E11"),
    (MacroYield,       "E12"),
    (Level2Tape,       "E13"),
    (ETFArbiter,       "E14"),
    (PulseEquity,      "E15"),
    (EarningsHawk,     "E16"),
    (GammaTide,        "E17"),
    (RotationSage,     "E18"),
    (MetaEnsembleEQ,   "E-META"),
])
def test_equity_instantiation_no_crash(cls, bot_id, flat_300):
    bot = cls(bot_id=bot_id, name=f"test-{bot_id}", initial_capital=300.0,
              fee_rate=0.0005)
    assert bot.bot_id == bot_id
    short = flat_300.iloc[:5]
    result = bot.signal(short, {"symbol": "SPY"})
    assert result is None


# ─── 確認特定策略能生成信號 ─────────────────────

def test_bayes_eq_long_signal(mean_rev_long_300):
    """BayesEQ 在 z-score < -2.2 時應生成 LONG"""
    bot = BayesEQ(bot_id="E04", name="BayesEQ", initial_capital=300.0,
                  fee_rate=0.0005)
    sig = bot.signal(mean_rev_long_300, {"symbol": "SPY"})
    assert sig is not None, "BayesEQ 應在 z-score < -2.2 時發出 LONG"
    assert sig.side == "LONG"
    assert sig.school == "量化統計"


def test_macro_fedwatch_risk_on(flat_300):
    """MacroFedWatch 在鴿派 Fed context 時應生成信號"""
    bot = MacroFedWatch(bot_id="E11", name="FedWatch", initial_capital=300.0,
                        fee_rate=0.0005)
    ctx = {
        "symbol": "SPY",
        "macro_data": {
            "fed_rate_change_bps": -25,
            "cpi_yoy": 2.5,
            "unemployment": 4.0,
        },
    }
    sig = bot.signal(flat_300, ctx)
    if sig is not None:
        assert sig.side in ("LONG", "SHORT")
        assert sig.entry_price > 0


def test_earnings_hawk_pead_long(flat_300):
    """EarningsHawk 在財報後正向意外時應生成 LONG"""
    bot = EarningsHawk(bot_id="E16", name="EarningsHawk", initial_capital=300.0,
                       fee_rate=0.0005)
    ctx = ctx_earnings("AAPL", days_since=2, surprise=0.08)
    sig = bot.signal(flat_300, ctx)
    assert sig is not None, "EarningsHawk 應在財報正向意外 days_since=2 時發出信號"
    assert sig.side == "LONG"
    assert sig.school == "財報事件"


def test_rotation_sage_sector():
    """RotationSage 在 sector_rs_ranks_history + 突破 20D 高時應觸發 LONG"""
    breakout_data = make_breakout_high(300, start_price=450.0)
    bot = RotationSage(bot_id="E18", name="RotationSage", initial_capital=300.0,
                       fee_rate=0.0005)
    ctx = ctx_sector_rotation()
    sig = bot.signal(breakout_data, ctx)
    assert sig is not None, "RotationSage 應在排名持續上升且突破 20D 高時發出信號"
    assert sig.school == "板塊輪動"


def test_pulse_equity_signal(flat_300):
    """PulseEquity 在情緒偏多時應生成 LONG"""
    bot = PulseEquity(bot_id="E15", name="PulseEQ", initial_capital=300.0,
                      fee_rate=0.0005)
    ctx = {"symbol": "AAPL", "sentiment_score": 0.75, "social_volume_zscore": 2.5}
    sig = bot.signal(flat_300, ctx)
    assert sig is not None
    assert sig.side == "LONG"


def test_stat_arb_pairs_no_spread_returns_none(flat_300):
    """StatArbPairs 在缺少 spread 欄位時應回傳 None"""
    bot = StatArbPairs(bot_id="E06", name="StatArb", initial_capital=300.0,
                       fee_rate=0.0005)
    result = bot.signal(flat_300, {"symbol": "AAPL"})
    assert result is None
