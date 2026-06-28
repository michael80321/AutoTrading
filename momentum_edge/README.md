# 動量 Edge 驗證工具

> 這不是「會賺錢的動量交易機器人」。這是一個**誠實告訴你：純動量策略在加密貨幣上，扣掉成本之後到底有沒有 edge** 的驗證工具。
>
> 工程上的每個決定都服務「揭露真相」，而不是「讓回測曲線變漂亮」。許多設計**刻意讓結果變難看、刻意不給你調參數的空間** —— 那不是 bug，是核心價值。

## 它幫你回答的唯一問題

> 在我花真錢之前 —— 純動量策略，扣掉手續費與滑價之後，**贏得過單純抱著 BTC（Buy & Hold）嗎？**

如果樣本外（OOS）扣成本後贏不過 B&H，答案就是「沒有 edge」。這個答案本身就值回票價，它幫你擋掉下一筆真金白銀。

## 策略：時間序列動量 (TSMOM)

- 第 t 天收盤算過去 `N=90` 天累積報酬：`close[t]/close[t-N] - 1`
- `> 0` → 滿倉做多（100%）；`≤ 0` → 空手持現金（0%）
- **不做空、不開槓桿、不調整部位大小**（把訊號的 edge 跟部位管理技巧分離，單獨檢驗訊號）

## 安裝

```bash
pip install pandas numpy matplotlib ccxt
```

## 使用

```bash
# 用鎖定預設 N=90，pre-registered 單組（推薦）
python -m momentum_edge.run

# 換標的（僅白名單 BTC/USDT, ETH/USDT，控管倖存者偏誤）
python -m momentum_edge.run --symbol ETH/USDT

# 離線：只用先前抓好的快取
python -m momentum_edge.run --no-fetch

# 教育用：跑 N∈{30,60,90} 對照（會強制觸發多重測試警語，不可拿來挑一組上實盤）
python -m momentum_edge.run --audit-Ns
```

輸出：
- `output/report_<TAG>.csv` — IS / OOS / 全期 × 策略 / B&H 全部指標（分開，不合併）
- `output/equity_<TAG>.png` — 策略 vs B&H 權益疊圖，標出 IS/OOS 分界線

> 網路被封鎖時，`fetch()` 會自動退回 `data_cache/` 的快取；若無快取則明確報錯，**絕不**用假資料硬跑。

## 防過擬合護欄（工具的良心）

| 護欄 | 實作 |
|---|---|
| 參數鎖死 | `config.N=90` 寫死；改了就在報表頂端印過擬合警語 |
| IS/OOS 嚴格分離 | `split()` 依時間前 60% IS、後 40% OOS；OOS 在參數鎖定後才碰，結果分開印 |
| 多重測試揭露 | 試多組 N → 報表記錄「試了幾組」並印 data-snooping 警語 |
| 禁未來函數 | 訊號用 t(含)前資料；成交在 **t+1 開盤**；有測試竄改未來資料證明不影響過去 |
| 倖存者偏誤 | 只測白名單長壽標的 |
| 成本不可歸零 | `fee/slip ≤ 0` → 直接 `ValueError`，拒絕執行 |

## 報表的三個重點

1. **主判準**：扣成本後總報酬 vs Buy & Hold（贏不過 = 沒有 edge）
2. **工具的靈魂**：回測(IS) vs 樣本外(OOS) vs 落差（落差越大 = 回測越在騙人）
3. **角落**：勝率僅供參考，明確標註不可作為決策依據（勝率高 ≠ 賺錢）

## 模組結構

```
config.py          鎖定參數 + 改動偵測
data_layer/        fetch（ccxt+快取）→ clean（報出問題不默默補）→ split（嚴格時間切分）
strategy_layer/    tsmom_signal（0/1 部位，禁未來函數）
eval_layer/        backtest（t+1 成交、強制扣成本）→ buy_and_hold → metrics → report
run.py             資料流 1→8 主流程
tests/test_engine.py  引擎正確性測試（含驗收標準 #1 #2，不需網路）
```

## 驗收標準對照

| # | 標準 | 驗證方式 |
|---|---|---|
| 1 | fee=0 → 拒絕執行報錯 | `test_fee_zero_rejected` ✅ |
| 2 | 無「t 訊號 t 收盤成交」路徑 | `test_fill_happens_at_next_open_not_signal_close`、`test_no_lookahead_...` ✅ |
| 3 | 報表同時有策略與 B&H 兩條線 | `report()` 疊圖 + 主判準三段 ✅ |
| 4 | IS/OOS 指標分開、不合併 | CSV 六欄分開、終端分段印 ✅ |
| 5 | 報表頂端三行警語 | `_warning_header()`，CSV/終端皆印 ✅ |
| 6 | 主畫面是「扣成本後 vs B&H」、勝率在角落有但書 | `report()` 版面 ✅ |

跑測試：
```bash
python -m momentum_edge.tests.test_engine
```

## 明確不做（Non-Goals）

❌ 不接真實下單、不碰真錢　❌ 不做參數最佳化器/grid search　❌ 不做多策略共識/演化淘汰　❌ 不追求高勝率　❌ 第一版不做漂亮 dashboard

## 之後（Phase 2）

`live paper-trading harness`：每天收盤自動跑、產生明日訊號、虛擬倉記帳，累積完全未被參數選擇污染的「向前走」真相紀錄。
