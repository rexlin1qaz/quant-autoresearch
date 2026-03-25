"""
Quant Research — Strategy Definition (ONLY FILE YOU SHOULD EDIT)
=================================================================
Goal: maximize  composite_score = Sortino × (1 - Max_Drawdown)

Approach: 「籌碼積累突破」策略
  1. 找出股票在一段時間的價格停留區間（籌碼積累）
  2. 當股價以明顯量能突破積累區間高點時進場做多
  3. 以 ATR 移動停損控制下行風險

Usage:
    uv run strategy.py          → run backtest, print results, write results.tsv
"""

import subprocess
from pathlib import Path

from prepare import (
    evaluate,
    load_universe,
    print_results,
    BacktestResult,
)
import pandas as pd

# ---------------------------------------------------------------------------
# STRATEGY PARAMETERS  ← Agent: edit these freely
# ---------------------------------------------------------------------------

# ── Accumulation / Consolidation Detection ──────────────────────────────────
CONSOLIDATION_DAYS    = 20    # lookback window to measure the accumulation zone
CONSOLIDATION_TIGHTNESS = 0.05  # max range_pct to qualify as "tight" (8% of price)

# ── Breakout Entry ───────────────────────────────────────────────────────────
BREAKOUT_LOOKBACK     = 20    # N-day high used to define resistance level
VOLUME_LOOKBACK       = 20    # rolling window for average volume baseline
VOLUME_SURGE_RATIO    = 2.0   # entry requires today's volume > N × 20d avg
REQUIRE_ABOVE_MA20    = True  # extra trend filter: only trade above 20d MA
REQUIRE_ABOVE_MA60    = False # extra trend filter: only trade above 60d MA

# ── Risk Management ──────────────────────────────────────────────────────────
ATR_PERIOD            = 14    # ATR calculation period (Wilder EMA)
STOP_LOSS_ATR         = 2.5   # initial stop = entry_price - N × ATR
TRAILING_STOP_ATR     = 2.0   # trailing stop = peak_price - N × ATR
MAX_HOLD_DAYS         = 30    # close position after N trading days regardless

# ── Portfolio / Universe Filters ─────────────────────────────────────────────
MAX_POSITIONS         = 5     # max concurrent long positions
MIN_PRICE             = 10.0  # skip stocks cheaper than this (NT$)
MIN_VOLUME            = 500   # min avg daily volume (in 100-share lots)


# ---------------------------------------------------------------------------
# ENTRY SIGNAL LOGIC  ← Agent: you may modify this function
# ---------------------------------------------------------------------------

def compute_entry_signal(features_df: pd.DataFrame, params: dict) -> pd.Series:
    """
    Given pre-computed features for one stock (up to current date, no look-ahead),
    return a boolean Series where True means 'enter long on the NEXT bar's open'.

    Available columns in features_df (computed by prepare.py):
        open, high, low, close, volume               — raw OHLCV
        atr                                          — Average True Range
        consol_high, consol_low, range_pct           — accumulation zone metrics
        vol_ratio                                    — today's vol / N-day avg vol
        prior_high                                   — N-day high (prior period)
        breakout                                     — close > prior_high (bool)
        ma20, ma60                                   — moving averages
        above_ma20, above_ma60                       — price vs MA (bool)
        body_strength                                — (close-open)/(high-low)
    """
    c        = params.get("CONSOLIDATION_TIGHTNESS", CONSOLIDATION_TIGHTNESS)
    vol_thr  = params.get("VOLUME_SURGE_RATIO",      VOLUME_SURGE_RATIO)
    ma20_req = params.get("REQUIRE_ABOVE_MA20",      REQUIRE_ABOVE_MA20)
    ma60_req = params.get("REQUIRE_ABOVE_MA60",      REQUIRE_ABOVE_MA60)

    sig = (
        features_df["breakout"]                        # price breaks above N-day high
        & (features_df["vol_ratio"]   > vol_thr)       # with volume surge
        & (features_df["range_pct"]   < c)             # after tight consolidation
        & (features_df["body_strength"] > 0)           # bullish candle body
    )
    if ma20_req:
        sig = sig & features_df["above_ma20"]
    if ma60_req:
        sig = sig & features_df["above_ma60"]

    return sig.fillna(False)


# ---------------------------------------------------------------------------
# Build params dict from module-level constants
# ---------------------------------------------------------------------------

def get_params() -> dict:
    return dict(
        CONSOLIDATION_DAYS    = CONSOLIDATION_DAYS,
        CONSOLIDATION_TIGHTNESS = CONSOLIDATION_TIGHTNESS,
        BREAKOUT_LOOKBACK     = BREAKOUT_LOOKBACK,
        VOLUME_LOOKBACK       = VOLUME_LOOKBACK,
        VOLUME_SURGE_RATIO    = VOLUME_SURGE_RATIO,
        REQUIRE_ABOVE_MA20    = REQUIRE_ABOVE_MA20,
        REQUIRE_ABOVE_MA60    = REQUIRE_ABOVE_MA60,
        ATR_PERIOD            = ATR_PERIOD,
        STOP_LOSS_ATR         = STOP_LOSS_ATR,
        TRAILING_STOP_ATR     = TRAILING_STOP_ATR,
        MAX_HOLD_DAYS         = MAX_HOLD_DAYS,
        MAX_POSITIONS         = MAX_POSITIONS,
        MIN_PRICE             = MIN_PRICE,
        MIN_VOLUME            = MIN_VOLUME,
    )


# ---------------------------------------------------------------------------
# Main — run backtest and record results
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import time

    params = get_params()

    print("=" * 70)
    print("Quant Research — Breakout After Accumulation Strategy")
    print("=" * 70)
    print("Parameters:")
    for k, v in params.items():
        print(f"  {k:<26} = {v}")
    print()

    t0 = time.time()
    universe = load_universe()
    r_in, r_out = evaluate(compute_entry_signal, params, universe)
    elapsed = time.time() - t0

    print()
    print("─" * 70)
    print_results("IN-SAMPLE", r_in)
    print_results("OUT-SAMPLE", r_out)
    print("─" * 70)
    print(f"Backtest completed in {elapsed:.1f}s")
    print()

    # ── Log to results.tsv ─────────────────────────────────────────────────
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        commit = "no-git"

    results_path = Path(__file__).parent / "results.tsv"
    row = (
        f"{commit}\t"
        f"{r_out.composite:.6f}\t"
        f"{r_out.sortino:.6f}\t"
        f"{r_out.max_drawdown*100:.2f}%\t"
        f"{r_out.win_rate*100:.1f}%\t"
        f"{r_out.num_trades}\t"
        f"{r_in.composite:.6f}\t"
        f"(description)\n"
    )
    # Append row
    with open(results_path, "a", encoding="utf-8") as f:
        f.write(row)

    print(f"Results written to {results_path.name}")
    print()
    print("PRIMARY METRIC  (out-of-sample composite) :", r_out.composite)
    print("  → higher is better. Next step: modify parameters above and re-run.")
