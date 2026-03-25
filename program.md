# quant-research

## 核心理念

這是一個**自主量化交易研究框架**。AI Agent 持續修改策略參數、執行回測、評估結果、保留進步、丟棄退步——讓整個研究循環在無人監督下運行。

**研究目標**：找出能讓資金曲線「穩定階梯式上升」的台股波段策略。  
**優化指標**：`composite_score = Sortino × (1 - Max_Drawdown)`（越高越好）

## 策略核心思路

**籌碼積累突破**（Breakout After Accumulation）：
1. 辨識股票在一段時間內價格在窄幅區間橫盤的「積累期」（smart money 悄悄佈局）
2. 當股價以明顯量能突破積累高點時進場做多
3. 以 ATR 移動停損嚴格控制下行風險，「保住獲利」比「賺更多」更重要

## 檔案架構

```
strategy.py   — Agent 唯一可修改的檔案（策略參數 + 進場訊號邏輯）
prepare.py    — 固定不動（資料載入、特徵工程、回測引擎、評估函數）
program.md    — 本檔（Agent 指引）
results.tsv   — 實驗記錄
data/*.csv    — 200 支台股日線 OHLCV 資料
```

## 設置（每次新實驗前執行一次）

1. **確認分支**：提議本次實驗 tag（如 `mar25`），切換到 `autoresearch/<tag>` 分支
   ```bash
   git checkout -b autoresearch/mar25
   ```

2. **閱讀核心檔案**：
   - `prepare.py` — 了解可用的 features、回測邏輯、BacktestResult 欄位
   - `strategy.py` — 確認現有基準參數

3. **驗證資料存在**：
   ```bash
   ls data/ | head -5
   ```

4. **初始化 results.tsv**（若尚未建立）：
   ```
   commit	composite_out	sortino_out	mdd_out	win_rate_out	trades_out	composite_in	description
   ```

5. **執行基準實驗**，確認環境正常：
   ```bash
   uv run strategy.py
   ```

6. 確認輸出正常後，開始實驗循環。

## 實驗循環

```
LOOP FOREVER:

1. 查看現在的 git 狀態與 results.tsv
2. 提出一個具體的研究假設（例如：「縮緊 range_pct 閾值可能提升訊號品質」）
3. 修改 strategy.py（僅修改此檔案）
4. git commit
5. 執行回測：
     uv run strategy.py
6. 讀取 results.tsv 最新一行，比較 composite_out
7. 若 composite_out 提升 → 保留（繼續在此分支上累積）
   若 composite_out 退步 → git reset --hard HEAD~1（回到上一個 commit）
8. 回到步驟 1
```

## 可修改範圍

**可以做的事：**
- 修改 `strategy.py` 中任何參數或進場邏輯
- 新增 `strategy.py` 中的輔助訊號條件
- 嘗試任何參數的組合

**禁止做的事：**
- 修改 `prepare.py`（這是評估地基，動了就不公平了）
- 修改交易成本、時間分割點、Sortino 計算方式
- 安裝新套件

## 研究方向建議

以下是有機會改善 composite_score 的研究方向，依優先順序排列：

### 訊號品質（進場篩選）
- **縮緊 `CONSOLIDATION_TIGHTNESS`**：更嚴格的積累區間定義，提升訊號純度
- **調整 `VOLUME_SURGE_RATIO`**：突破時量能是否越大越好？還是適中即可？
- **加入 `REQUIRE_ABOVE_MA60`**：大趨勢過濾，只做多頭格局中的突破
- **`body_strength` 門檻**：突破當日的陽線力道是否應有最低要求？

### 風險管理（停損策略）
- **調整 `STOP_LOSS_ATR`**：初始停損寬一點容許波動？還是緊一點降低損失？
- **調整 `TRAILING_STOP_ATR`**：移動停損太緊會被洗出，太鬆會吐回利潤
- **`MAX_HOLD_DAYS`**：30 天是否適當？波段策略的典型持有時間？

### 投資組合管理
- **`MAX_POSITIONS`**：集中持倉 (3) vs 分散持倉 (8)？
- **進場排序**：當多個訊號同時出現時，如何選擇哪幾支先進場？
  （目前為 `range_pct` 最緊的優先，可改為成交量最大、ATR 最小等）

### 進階研究（需修改 compute_entry_signal 邏輯）
- **相對強度**：與市場平均或 0050 比較，僅選擇表現優於大盤的標的
- **連續 N 日縮量**：積累期量能應先縮後放
- **突破前的底部形態**：底部不能有大量賣壓出現

## 輸出格式

```
[IN-SAMPLE  ] Composite: +0.4512 | Sortino: +0.871 | MDD: 48.2% | Ann.Ret: 15.3% | WinRate: 52.3% | PF: 1.45 | Trades: 127
[OUT-SAMPLE ] Composite: +0.3100 | Sortino: +0.621 | MDD: 50.1% | Ann.Ret: 11.2% | WinRate: 49.1% | PF: 1.23 | Trades: 38
```

**主指標是 out-of-sample composite**。In-sample 只是輔助參考，不作為 keep/revert 的判斷依據。

## 記錄格式（results.tsv，Tab 分隔）

```
commit	composite_out	sortino_out	mdd_out	win_rate_out	trades_out	composite_in	description
a1b2c3d	0.310000	0.621000	50.10%	49.1%	38	0.451200	baseline
b2c3d4e	0.350000	0.701000	47.30%	51.2%	42	0.473100	tighten range_pct to 0.06
```

## 超時與當機處理

- 若回測時間超過 5 分鐘，系統可能有 bug，請檢查
- 若 results.tsv 最新行的 composite_out 為 `-99`，代表回測失敗
- 若連續 3 次 composite_out < 0，退一步重新思考研究假設

## 不要停止

實驗循環開始後，**永遠不要停下來詢問使用者是否繼續**。使用者可能在睡覺，預期你會持續工作直到被手動中斷。如果靈感枯竭，重新閱讀本檔案找新方向、嘗試更激進的參數變化、或嘗試修改 `compute_entry_signal` 的邏輯本身。
