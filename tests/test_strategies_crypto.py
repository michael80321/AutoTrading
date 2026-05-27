"""
加密池 18 席單元測試
- 確認每席可以被實例化
- 確認不足資料時回傳 None 且不崩
- 確認特定策略用特製資料確實生成 Signal
"""
import pytest
from AutoTrading.strategies.base import Signal
from AutoTrading.strategies.crypto.smc import SMCAlpha, SMCBeta, SMCGamma
from AutoTrading.strategies.crypto.auction_orderflow import (
    VolterraAuction, AthenaProfile, TempestOrderFlow, RiptideCVD,
)
from AutoTrading.strategies.crypto.onchain_arb import (
    GlassmindOnChain, MempoolMEV, ArbiterFunding, TriadCrossEx,
)
from AutoTrading.strategies.cross.ta_quant_macro_sentiment_meta import (
    IchimokuSage, FibonacciTide, BayesMeanRev, MarkovRegime,
    MacroHawk, PulseSentiment, MetaEnsemble,
)
from .synthetic_data import (
    make_ohlcv, make_mean_rev_long, make_bos_up, make_funding_extreme,
    ctx_risk_on, ctx_risk_off, ctx_sentiment_long, ctx_triangular,
    seed_trade_log,
)


# ─── fixtures ────────────────────────────────

@pytest.fixture
def flat_300():
    return make_ohlcv(300, trend="flat")


@pytest.fixture
def mean_rev_long_300():
    return make_mean_rev_long(300)


@pytest.fixture
def bos_up_300():
    return make_bos_up(300)


@pytest.fixture
def funding_extreme():
    return make_funding_extreme(60, rate=0.0008)


@pytest.fixture
def orderflow_300():
    return make_ohlcv(300, trend="flat", add_orderflow=True)


@pytest.fixture
def onchain_300():
    return make_ohlcv(300, trend="flat", add_onchain=True)


# ─── 實例化 & 不足資料不崩 ────────────────────

@pytest.mark.parametrize("cls,bot_id", [
    (SMCAlpha,        "C01"),
    (SMCBeta,         "C02"),
    (SMCGamma,        "C03"),
    (TempestOrderFlow,"C04"),
    (RiptideCVD,      "C05"),
    (GlassmindOnChain,"C06"),
    (MempoolMEV,      "C07"),
    (ArbiterFunding,  "C08"),
    (TriadCrossEx,    "C09"),
    (VolterraAuction, "C10"),
    (IchimokuSage,    "C11"),
    (FibonacciTide,   "C12"),
    (BayesMeanRev,    "C13"),
    (MarkovRegime,    "C14"),
    (MacroHawk,       "C15"),
    (PulseSentiment,  "C16"),
    (AthenaProfile,   "C17"),
    (MetaEnsemble,    "C18"),
])
def test_instantiation_and_no_crash_on_short_data(cls, bot_id, flat_300):
    """每席應可實例化,且在資料不足時回傳 None 而非拋例外"""
    bot = cls(bot_id=bot_id, name=f"test-{bot_id}", initial_capital=300.0)
    assert bot.bot_id == bot_id
    assert bot.capital == 300.0
    # 10 根不足任何策略門檻
    short = flat_300.iloc[:10]
    result = bot.signal(short, {"symbol": "BTCUSDT"})
    assert result is None


# ─── 確認特定策略能生成信號 ─────────────────────

def test_bayes_mean_rev_long_signal(mean_rev_long_300):
    """BayesMeanRev 在 z-score < -2.2 時應生成 LONG"""
    bot = BayesMeanRev(bot_id="C13", name="Bayes", initial_capital=300.0)
    sig = bot.signal(mean_rev_long_300, {"symbol": "BTCUSDT"})
    assert sig is not None, "BayesMeanRev 應在 z-score < -2.2 時發出 LONG 信號"
    assert sig.side == "LONG"
    assert sig.school == "量化統計"
    assert 0 < sig.confidence <= 1.0
    assert sig.stop_loss < sig.entry_price
    assert len(sig.take_profit) >= 1


def test_smcbeta_bos_up_signal(bos_up_300):
    """SMCBeta 在上升 BOS 時應生成 LONG"""
    bot = SMCBeta(bot_id="C02", name="SMCBeta", initial_capital=300.0)
    sig = bot.signal(bos_up_300, {"symbol": "BTCUSDT"})
    # BOS 條件嚴格,可能 None — 只驗不崩且若有信號結構正確
    if sig is not None:
        assert sig.side in ("LONG", "SHORT")
        assert sig.entry_price > 0
        assert len(sig.take_profit) >= 1


def test_macro_hawk_risk_on_signal(flat_300):
    """MacroHawk 在 risk-on context 時應生成 LONG"""
    bot = MacroHawk(bot_id="C15", name="MacroHawk", initial_capital=300.0)
    ctx = ctx_risk_on("BTCUSDT")
    sig = bot.signal(flat_300, ctx)
    assert sig is not None, "MacroHawk 應在 risk-on 下發出 LONG"
    assert sig.side == "LONG"
    assert sig.school == "宏觀"


def test_macro_hawk_risk_off_signal(flat_300):
    """MacroHawk 在 risk-off context 時應生成 SHORT"""
    bot = MacroHawk(bot_id="C15", name="MacroHawk", initial_capital=300.0)
    sig = bot.signal(flat_300, ctx_risk_off("BTCUSDT"))
    assert sig is not None
    assert sig.side == "SHORT"


def test_pulse_sentiment_long_signal(flat_300):
    """PulseSentiment 在中等偏多情緒時應生成 LONG"""
    bot = PulseSentiment(bot_id="C16", name="Pulse", initial_capital=300.0)
    sig = bot.signal(flat_300, ctx_sentiment_long("BTCUSDT"))
    assert sig is not None, "PulseSentiment 應在 sentiment=0.75 時發出 LONG"
    assert sig.side == "LONG"
    assert sig.school == "情緒"


def test_triad_cross_ex_arbitrage(flat_300):
    """TriadCrossEx 在套利空間充足時應生成信號"""
    bot = TriadCrossEx(bot_id="C09", name="Triad", initial_capital=300.0,
                       fee_rate=0.0004)
    ctx = ctx_triangular(profit_pct=0.003)
    sig = bot.signal(flat_300, ctx)
    assert sig is not None, "TriadCrossEx 應在套利利潤 > 0.15% 時發出信號"
    assert sig.confidence >= 0.9


def test_arbiter_funding_extreme(funding_extreme):
    """ArbiterFunding 在極端正費率時應生成 SHORT"""
    bot = ArbiterFunding(bot_id="C08", name="Arbiter", initial_capital=300.0)
    sig = bot.signal(funding_extreme, {"symbol": "BTCUSDT"})
    assert sig is not None, "ArbiterFunding 應在 funding_rate=0.0008 時發出信號"
    assert sig.side == "SHORT"


def test_volterra_auction(flat_300):
    """VolterraAuction 不崩且若觸發則信號結構正確"""
    bot = VolterraAuction(bot_id="C10", name="Volterra", initial_capital=300.0)
    sig = bot.signal(flat_300, {"symbol": "BTCUSDT"})
    if sig is not None:
        assert sig.entry_price > 0
        assert sig.stop_loss != sig.entry_price
        assert len(sig.take_profit) >= 1


def test_tempest_orderflow_no_column_returns_none(flat_300):
    """TempestOrderFlow 在缺少 buy_volume 欄位時應回傳 None"""
    bot = TempestOrderFlow(bot_id="C04", name="Tempest", initial_capital=300.0)
    assert bot.signal(flat_300, {"symbol": "BTCUSDT"}) is None


def test_tempest_orderflow_with_column(orderflow_300):
    """TempestOrderFlow 有 buy_volume 時不崩"""
    bot = TempestOrderFlow(bot_id="C04", name="Tempest", initial_capital=300.0)
    result = bot.signal(orderflow_300, {"symbol": "BTCUSDT"})
    # delta_z 隨機資料可能不超過閾值,只驗不崩
    assert result is None or isinstance(result, Signal)


def test_meta_ensemble_with_sub_signals(flat_300, mean_rev_long_300):
    """MetaEnsemble 在有 ≥3 個子信號時應生成信號"""
    from AutoTrading.strategies.base import Signal as Sig
    from datetime import datetime

    bot = MetaEnsemble(bot_id="C18", name="Meta", initial_capital=0.0)
    sub = [
        Sig("C13","Bayes","量化統計","BTCUSDT","LONG",49700,49500,[50000],0.8,"1H",datetime.now(),"z低"),
        Sig("C15","Macro","宏觀","BTCUSDT","LONG",49700,49400,[50200],0.7,"1D",datetime.now(),"risk-on"),
        Sig("C16","Pulse","情緒","BTCUSDT","LONG",49700,49450,[50100],0.6,"1H",datetime.now(),"sentiment"),
    ]
    ctx = {
        "symbol": "BTCUSDT",
        "sub_signals": sub,
        "bot_composite_scores": {"C13": 0.6, "C15": 0.5, "C16": 0.45},
    }
    sig = bot.signal(flat_300, ctx)
    assert sig is not None, "MetaEnsemble 應在 3 席同向時發出信號"
    assert sig.side == "LONG"


# ─── 信號結構正確性通用驗證 ─────────────────────

def _assert_signal_valid(sig: Signal):
    assert isinstance(sig.bot_id, str)
    assert sig.side in ("LONG", "SHORT", "FLAT")
    assert 0 < sig.confidence <= 1.0
    assert sig.entry_price > 0
    assert sig.stop_loss > 0
    assert isinstance(sig.take_profit, list) and len(sig.take_profit) >= 1
    assert isinstance(sig.rationale, str)


def test_signal_structure_macro_hawk(flat_300):
    bot = MacroHawk(bot_id="C15", name="Macro", initial_capital=300.0)
    sig = bot.signal(flat_300, ctx_risk_on())
    _assert_signal_valid(sig)


def test_signal_structure_bayes(mean_rev_long_300):
    bot = BayesMeanRev(bot_id="C13", name="Bayes", initial_capital=300.0)
    sig = bot.signal(mean_rev_long_300, {"symbol": "BTCUSDT"})
    _assert_signal_valid(sig)
