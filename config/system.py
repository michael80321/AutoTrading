"""
中央配置 — 雙池架構 (加密 18 席 + 美股 18 席 = 36 席)
"""
from dataclasses import dataclass, field


@dataclass
class CapitalConfig:
    # 兩池完全獨立
    crypto_pool_total: float = 5400.0   # 18 席 × 300 USDT
    stock_pool_total: float = 5400.0    # 18 席 × 300 USD
    per_bot_initial: float = 300.0
    fee_rate_crypto: float = 0.0004     # Binance taker
    fee_rate_stock: float = 0.0005      # IBKR US stock
    slippage_pct: float = 0.0005


@dataclass
class ConsensusConfig:
    min_aligned_schools: int = 2      # 2 派同向即可開單（初期收集實戰數據，原為 3）
    min_total_weight: float = 1.0     # 配合 2 派的加權總分門檻（原為 1.5）
    min_backtest_winrate: float = 0.58
    max_risk_per_trade_pct: float = 0.015
    ewma_alpha: float = 0.7


@dataclass
class EvolutionConfig:
    cycle_days: int = 30
    bottom_pct: float = 0.15
    top_pct: float = 0.10
    consecutive_bottom_to_retire: int = 2
    sandbox_min_backtest_months: int = 18
    breed_competition_days: int = 90
    mutation_rate: float = 0.10


# ============================================================
# 加密池 18 席
# ============================================================
CRYPTO_ROSTER = [
    {"id": "C01", "name": "小騏 SMC-Alpha",     "school": "SMC",      "class": "SMCAlpha",          "module": "strategies.crypto.smc"},
    {"id": "C02", "name": "Orion SMC-Beta",     "school": "SMC",      "class": "SMCBeta",           "module": "strategies.crypto.smc"},
    {"id": "C03", "name": "Helix SMC-Gamma",    "school": "SMC",      "class": "SMCGamma",          "module": "strategies.crypto.smc"},
    {"id": "C04", "name": "Tempest OF-Live",    "school": "訂單流",    "class": "TempestOrderFlow",  "module": "strategies.crypto.auction_orderflow"},
    {"id": "C05", "name": "Riptide OF-Quant",   "school": "訂單流",    "class": "RiptideCVD",        "module": "strategies.crypto.auction_orderflow"},
    {"id": "C06", "name": "Glassmind OnChain",  "school": "鏈上",      "class": "GlassmindOnChain",  "module": "strategies.crypto.onchain_arb"},
    {"id": "C07", "name": "Mempool MEV",        "school": "鏈上",      "class": "MempoolMEV",        "module": "strategies.crypto.onchain_arb"},
    {"id": "C08", "name": "Arbiter Funding",    "school": "套利",      "class": "ArbiterFunding",    "module": "strategies.crypto.onchain_arb"},
    {"id": "C09", "name": "Triad Cross-Ex",     "school": "套利",      "class": "TriadCrossEx",      "module": "strategies.crypto.onchain_arb"},
    {"id": "C10", "name": "Volterra Auction",   "school": "拍賣理論",  "class": "VolterraAuction",   "module": "strategies.crypto.auction_orderflow"},
    {"id": "C11", "name": "Ichimoku Sage",      "school": "傳統TA",    "class": "IchimokuSage",      "module": "strategies.cross.ta_quant_macro_sentiment_meta"},
    {"id": "C12", "name": "Fibonacci Tide",     "school": "傳統TA",    "class": "FibonacciTide",     "module": "strategies.cross.ta_quant_macro_sentiment_meta"},
    {"id": "C13", "name": "Bayes Mean-Rev",     "school": "量化統計",  "class": "BayesMeanRev",      "module": "strategies.cross.ta_quant_macro_sentiment_meta"},
    {"id": "C14", "name": "Markov Regime",      "school": "量化統計",  "class": "MarkovRegime",      "module": "strategies.cross.ta_quant_macro_sentiment_meta"},
    {"id": "C15", "name": "Macro Hawk",         "school": "宏觀",      "class": "MacroHawk",         "module": "strategies.cross.ta_quant_macro_sentiment_meta"},
    {"id": "C16", "name": "Pulse Sentiment",    "school": "情緒",      "class": "PulseSentiment",    "module": "strategies.cross.ta_quant_macro_sentiment_meta"},
    {"id": "C17", "name": "Athena Profile",     "school": "拍賣理論",  "class": "AthenaProfile",     "module": "strategies.crypto.auction_orderflow"},
    {"id": "C18", "name": "Meta Ensemble (加密)", "school": "AI 元學派", "class": "MetaEnsemble",      "module": "strategies.cross.ta_quant_macro_sentiment_meta"},
]

# ============================================================
# 美股池 18 席 — 結構不同,加入專屬學派
# ============================================================
STOCK_ROSTER = [
    # 拍賣理論 ×3
    {"id": "E01", "name": "Volterra-EQ",        "school": "拍賣理論",  "class": "VolterraEQ",        "module": "strategies.stock.equity_core"},
    {"id": "E02", "name": "Athena-EQ",          "school": "拍賣理論",  "class": "AthenaEQ",          "module": "strategies.stock.equity_core"},
    {"id": "E03", "name": "Auction-Composite",  "school": "拍賣理論",  "class": "AuctionComposite",  "module": "strategies.stock.equity_core"},
    # 量化統計 ×3
    {"id": "E04", "name": "Bayes-EQ",           "school": "量化統計",  "class": "BayesEQ",           "module": "strategies.stock.equity_core"},
    {"id": "E05", "name": "Markov-EQ",          "school": "量化統計",  "class": "MarkovEQ",          "module": "strategies.stock.equity_core"},
    {"id": "E06", "name": "StatArb Pairs",      "school": "量化統計",  "class": "StatArbPairs",      "module": "strategies.stock.equity_core"},
    # SMC ×2
    {"id": "E07", "name": "SMC-Equity-Alpha",   "school": "SMC",      "class": "SMCEquityAlpha",    "module": "strategies.stock.equity_core"},
    {"id": "E08", "name": "SMC-Equity-Beta",    "school": "SMC",      "class": "SMCEquityBeta",     "module": "strategies.stock.equity_core"},
    # 傳統 TA ×2
    {"id": "E09", "name": "Ichimoku-EQ",        "school": "傳統TA",    "class": "IchimokuEQ",        "module": "strategies.stock.equity_core"},
    {"id": "E10", "name": "Fibonacci-EQ",       "school": "傳統TA",    "class": "FibonacciEQ",       "module": "strategies.stock.equity_core"},
    # 宏觀 ×2
    {"id": "E11", "name": "Macro FedWatch",     "school": "宏觀",      "class": "MacroFedWatch",     "module": "strategies.stock.equity_core"},
    {"id": "E12", "name": "Macro Yield Curve",  "school": "宏觀",      "class": "MacroYield",        "module": "strategies.stock.equity_core"},
    # 訂單流 ×1
    {"id": "E13", "name": "Level2 Tape",        "school": "訂單流",    "class": "Level2Tape",        "module": "strategies.stock.equity_core"},
    # 套利 ×1
    {"id": "E14", "name": "ETF Arbiter",        "school": "套利",      "class": "ETFArbiter",        "module": "strategies.stock.equity_core"},
    # 情緒 ×1
    {"id": "E15", "name": "Pulse Equity",       "school": "情緒",      "class": "PulseEquity",       "module": "strategies.stock.equity_core"},
    # 美股專屬 ×3
    {"id": "E16", "name": "Earnings Hawk",      "school": "財報事件",  "class": "EarningsHawk",      "module": "strategies.stock.equity_specific"},
    {"id": "E17", "name": "Gamma Tide",         "school": "期權流",    "class": "GammaTide",         "module": "strategies.stock.equity_specific"},
    {"id": "E18", "name": "Rotation Sage",      "school": "板塊輪動",  "class": "RotationSage",      "module": "strategies.stock.equity_specific"},
    # Meta — 注意:Meta 是第 18 席,但這版我把它替換掉了 Rotation/Gamma/Earnings 三選一?
    # 實際上應該是 19 席,所以這裡讓 Meta-EQ 取代某一席,改為「組外裁判」由 main.py 直接呼叫
]

# Meta-EQ 設為「裁判」獨立載入,不佔 18 席名額,放在 stock pool 邏輯外
META_EQ = {"id": "E-META", "name": "Meta Ensemble (美股)", "school": "AI 元學派",
           "class": "MetaEnsembleEQ", "module": "strategies.stock.equity_core"}
META_CRYPTO = {"id": "C-META", "name": "Meta Ensemble (加密)", "school": "AI 元學派",
               "class": "MetaEnsemble", "module": "strategies.cross.ta_quant_macro_sentiment_meta"}


@dataclass
class SystemConfig:
    capital: CapitalConfig = field(default_factory=CapitalConfig)
    consensus: ConsensusConfig = field(default_factory=ConsensusConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    
    binance_testnet: bool = True
    ibkr_paper_trading: bool = True
    redis_url: str = "redis://localhost:6379"
    postgres_url: str = "postgresql://localhost/ai_trading"
    
    account_max_drawdown_pct: float = 0.20
    black_swan_circuit_breaker_pct: float = 0.08
    max_concurrent_positions_per_pool: int = 8
    
    # 跨池警示(獨立但會互相通知,不會自動聯動下單)
    enable_cross_pool_warnings: bool = True
