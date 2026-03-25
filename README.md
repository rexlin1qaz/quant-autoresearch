# quant-research

![teaser](progress.png)

自主量化交易研究框架（Taiwan Stock Breakout Strategy Research）。

AI Agent 全自主運行實驗循環：修改策略參數 → 執行回測 → 記錄結果 → 保留進步 → 丟棄退步。  
你醒來時，Agent 已跑完數十次實驗，留下最優的籌碼積累突破策略。

## 核心理念

- **策略方向**：籌碼積累（Accumulation）後的價格突破做多
- **資金管理**：極度重視「回撤控制」與「下行風險保護」
- **優化目標**：`composite_score = Sortino × (1 - Max_Drawdown)` — 越高越好
- **交易宇宙**：台股 200 支標的，日線 OHLCV 資料

## 快速開始

**需求**：Python 3.10+，[uv](https://docs.astral.sh/uv/)，無需 GPU。

```bash
# 1. 安裝依賴
uv sync

# 2. 執行基準回測（確認環境）
uv run strategy.py
```

## 啟動 Agent

在本目錄中開啟你的 AI Agent（Claude / Gemini），然後輸入：

```
請閱讀 program.md，協助我啟動一個新的量化研究實驗循環。
```

Agent 會：
1. 提議一個實驗分支名稱（如 `autoresearch/mar25`）
2. 建立分支並閱讀策略文件
3. 執行基準回測，記錄 baseline
4. 自主開始修改策略參數、評估結果、循環實驗

## 檔案架構

```
strategy.py   — Agent 唯一可修改的檔案（策略參數 + 進場訊號邏輯）
prepare.py    — 固定回測引擎（DO NOT MODIFY）
program.md    — Agent 研究指引
results.tsv   — 實驗結果記錄
data/*.csv    — 200 支台股日線 OHLCV（2024 年至今）
```

## 設計原則

- **唯一可修改檔案**：Agent 只碰 `strategy.py`，評估函數固定不動，結果可信
- **嚴格反前視偏差**：訊號在 T 日收盤計算，T+1 日開盤執行
- **真實交易成本**：買 0.1425% + 賣 0.1425% + 證交稅 0.3%（合計 ~0.585%）
- **樣本外驗證**：優化以樣本內為輔助，主指標取 out-of-sample composite

## 評估指標

| 指標 | 說明 |
|------|------|
| **composite_score** | `Sortino × (1 - MDD)`，主要優化目標 |
| sortino | 年化 Sortino Ratio（下行偏差標準化超額收益） |
| max_drawdown | 最大回撤（越小越好） |
| win_rate | 獲利交易佔比 |
| profit_factor | 總獲利 / 總虧損 |
| annual_return | 年化報酬率 |

## License

MIT
