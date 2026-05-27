# AI Trading Collective · 雙池 36 席分析師系統

> **加密池 18 席 + 美股池 18 席 = 36 席**,完全獨立運行,各自 9 大學派、$5,400 資金池、獨立聊天室、獨立進化排名。

## 雙池架構核心

| | 加密池 | 美股池 |
|---|---|---|
| 席次 | 18 + Meta 裁判 | 18 + Meta 裁判 |
| 資金 | $5,400 USDT | $5,400 USD |
| Broker | Binance | IBKR |
| 聊天室 | `#crypto-floor` | `#equities-floor` |
| 排名 | 池內獨立 | 池內獨立 |
| 共識門檻 | 各自 ≥3 派同向 | 各自 ≥3 派同向 |
| Meta 跨池 | ❌ 不跨池下單 | ❌ 不跨池下單 |
| 跨池警示 | ✅ 收到對方警示 | ✅ 收到對方警示 |

## 加密池 18 席學派分布

| 學派 | 席次 | 名稱 |
|---|---|---|
| SMC | 3 | Alpha / Beta / Gamma |
| 訂單流 | 2 | Tempest (Footprint) / Riptide (CVD) |
| 鏈上 | 2 | Glassmind / Mempool |
| 套利 | 2 | Arbiter (Funding) / Triad (跨所) |
| 傳統 TA | 2 | Ichimoku / Fibonacci |
| 量化統計 | 2 | Bayes / Markov |
| 拍賣理論 | 2 | Volterra / Athena |
| 宏觀 | 1 | Macro Hawk |
| 情緒 | 1 | Pulse Sentiment |
| AI 元 | 1 | Meta Ensemble (裁判,不佔執行席) |

## 美股池 18 席學派分布 (重新設計)

| 學派 | 席次 | 名稱 | 為什麼 |
|---|---|---|---|
| **拍賣理論** | **3** | Volterra-EQ / Athena-EQ / Auction-Composite | ES/NQ 期指是拍賣理論主場 |
| **量化統計** | **3** | Bayes-EQ / Markov-EQ / **StatArb Pairs** | 美股是量化的主場 |
| SMC | 2 | Equity-Alpha / Equity-Beta | 流動性 + BOS 同樣適用 |
| 傳統 TA | 2 | Ichimoku-EQ / Fibonacci-EQ | 個股技術面 |
| 宏觀 | 2 | FedWatch / Yield Curve | 美股對宏觀更敏感 |
| 訂單流 | 1 | Level2 Tape | Level 2 取得成本高 |
| 套利 | 1 | ETF Arbiter | ETF NAV vs 市價套利 |
| 情緒 | 1 | Pulse-Equity | WSB / FinTwit |
| **★ 財報事件** | **1** | **Earnings Hawk** | 美股獨有 PEAD + IV crush |
| **★ 期權流** | **1** | **Gamma Tide** | Dealer Gamma + 0DTE pin |
| **★ 板塊輪動** | **1** | **Rotation Sage** | 11 個 SPDR 板塊 ETF 強弱 |
| AI 元 | (外掛) | Meta-EQ Ensemble (裁判) | 不佔 18 席 |

★ 標示 = 美股池獨有,加密市場沒有對應物

## 跨池警示機制

兩池完全獨立下單,但會互相廣播狀態:
- 加密池單日回撤 >8% → 警示美股池(美股池可選擇性降低風險權重)
- 美股池 risk-off 訊號(VIX>25)→ 警示加密池
- 警示僅作為 context 注入,不會自動觸發對方平倉

## 動態權重公式 (兩池各自獨立)

```
新權重 = 0.7 × (0.3 + 綜合分數 × 1.7) + 0.3 × 學派基礎權重
綜合分數 = 0.35×標準化夏普 + 0.25×勝率 + 0.20×(1−MDD) + 0.20×月度穩定性
```

## 進化機制 (各池獨立排名)

- 30 天結算
- 池內後 15% → 沙盒重訓
- 池內連 2 週期墊底 → 永久退役
- 池內前 10% → 分裂繁衍 (±10% 變異,$300 競爭 90 天)
- 所有上線/復職都需通過 18 個月 walk-forward 正期望值

## 帳戶級總風控(唯一兩池共享)

- 兩池合計 MDD 上限 20%
- 單日合計 -8% 觸發黑天鵝熔斷
- 雙路由 broker API key 權限最小化

## 專案結構

```
ai_trading_collective/
├── main.py                              # DualPoolOrchestrator 主協調器
├── config/system.py                     # CRYPTO_ROSTER + STOCK_ROSTER + META_*
├── strategies/
│   ├── base.py
│   ├── crypto/                          # 加密池 18 席
│   │   ├── smc.py
│   │   ├── auction_orderflow.py
│   │   └── onchain_arb.py
│   ├── stock/                           # 美股池 18 席
│   │   ├── equity_core.py               # 共 15 席 (含配對交易、ETF 套利、宏觀加強)
│   │   └── equity_specific.py           # ★ 美股獨有 3 席 (財報/期權/輪動)
│   └── cross/
│       └── ta_quant_macro_sentiment_meta.py  # 跨池共用的 TA/量化/宏觀/情緒/Meta
├── engine/consensus.py                  # 共識引擎 (兩池各跑一個實例)
├── evolution/manager.py                 # 進化管理 (兩池各跑一個實例)
├── execution/router.py                  # 執行路由 (加密用 Binance / 美股用 IBKR)
└── backtest/walkforward.py              # 18 個月 walk-forward
```

## Claude Code 待補

1. **資料層**:Binance WebSocket + IEX/Polygon 即時 K 棒
2. **鏈上**:Glassnode API (加密池用)
3. **期權鏈**:Polygon Options / CBOE (美股 Gamma Tide 用)
4. **財報日曆**:Earnings Whispers / Estimize (美股 Earnings Hawk 用)
5. **板塊資料**:SPDR ETF 即時報價 (美股 Rotation Sage 用)
6. **情緒**:X API + Reddit API + WSB scraper + FinBERT
7. **後端**:FastAPI + Redis pub/sub + PostgreSQL/TimescaleDB
8. **前端**:Next.js 14,雙頁面切換 `/crypto` 和 `/equity`
9. **強化學習**:每席獨立 PPO/SAC policy

## 啟動順序

```bash
pip install ccxt ib_insync pandas numpy scikit-learn lightgbm \
            stable-baselines3 fastapi redis asyncpg

# 1. 雙池回測驗證
python -m ai_trading_collective.main --mode backtest --pool both

# 2. Paper trading (Binance testnet + IBKR paper)
python -m ai_trading_collective.main --mode paper --pool both

# 3. 單池實盤(風險控管,先上線一池跑 30 天)
python -m ai_trading_collective.main --mode live --pool crypto --confirm

# 4. 雙池實盤
python -m ai_trading_collective.main --mode live --pool both --confirm
```

## 實盤前必過清單

- [ ] 加密 18 席全部通過 18 個月 walk-forward
- [ ] 美股 18 席全部通過 18 個月 walk-forward (其中財報/期權/輪動需有對應歷史資料)
- [ ] Binance testnet 跑滿 30 天
- [ ] IBKR paper trading 跑滿 30 天
- [ ] 兩池聊天室 WebSocket 壓測
- [ ] 跨池警示機制驗證
- [ ] 帳戶級熔斷壓測
- [ ] Telegram 監控告警
