"""
Quant Research — CPU Backtest Engine (DO NOT MODIFY)
=====================================================
Fixed constants, data loading, feature engineering, and backtest evaluation.
This file is the ground truth — the agent only edits strategy.py.

Usage (from strategy.py):
    from prepare import evaluate, load_universe, DATA_DIR, IN_SAMPLE_END
"""

from __future__ import annotations
import warnings
from pathlib import Path
from typing import Callable, NamedTuple
import numpy as np
import pandas as pd
import scipy.stats  # noqa: F401 (imported for agent convenience)

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

# ---------------------------------------------------------------------------
# Constants (fixed — do not modify)
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"

# Time split: in-sample for tuning, out-of-sample for honest evaluation
IN_SAMPLE_END   = "2025-07-01"  # last in-sample date (exclusive)
OUT_SAMPLE_START = "2025-07-01"  # first out-of-sample date (inclusive)

# Taiwan stock transaction costs
COMMISSION_BUY  = 0.001425   # 0.1425% on buy side
COMMISSION_SELL = 0.001425   # 0.1425% on sell side
SEC_TAX         = 0.003      # 0.3% securities transaction tax on sell

ROUND_TRIP_COST = COMMISSION_BUY + COMMISSION_SELL + SEC_TAX  # ~0.585%

# Evaluation: annualisation factor & MAR for Sortino
TRADING_DAYS_PER_YEAR = 252
SORTINO_MAR = 0.0   # minimum acceptable daily return (0 = beat zero)

# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_stock(path: Path) -> pd.DataFrame | None:
    """Load a single CSV, returning clean OHLCV DataFrame or None on failure."""
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
        df = df.rename(columns={
            "Date": "date", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume",
        })
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
        df = df.set_index("date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = df.replace(0, np.nan).dropna()
        if len(df) < 60:
            return None
        return df
    except Exception:
        return None


def load_universe(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    """Load all stock CSVs from data_dir, return {ticker: ohlcv_df}."""
    universe = {}
    for path in sorted(data_dir.glob("*.csv")):
        ticker = path.stem
        df = load_stock(path)
        if df is not None:
            universe[ticker] = df
    print(f"Loaded {len(universe)} stocks from {data_dir}")
    return universe

# ---------------------------------------------------------------------------
# Feature Engineering
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_features(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute trading features from raw OHLCV.  All features are calculated
    without look-ahead bias (each value uses only past data).

    Added columns (prefix meanings):
      atr_N         — ATR with period N
      vol_ratio_M   — rolling volume vs M-day average
      high_N        — N-day rolling high (shifted 1, so it's the *prior* N-day high)
      range_pct_N   — (N-day high - N-day low) / close  (prior N days)
      breakout_N    — True when close > prior N-day high
      rs_20         — relative strength: stock return vs universe average MA20
    """
    f = df.copy()
    atr_period   = params.get("ATR_PERIOD", 14)
    consol_days  = params.get("CONSOLIDATION_DAYS", 20)
    break_look   = params.get("BREAKOUT_LOOKBACK", 20)
    vol_look     = params.get("VOLUME_LOOKBACK", 20)

    f["atr"] = _atr(df, atr_period)

    # Consolidation measurement (prior N days, no look-ahead)
    roll_high = df["high"].rolling(consol_days).max().shift(1)
    roll_low  = df["low"].rolling(consol_days).min().shift(1)
    f["consol_high"] = roll_high
    f["consol_low"]  = roll_low
    f["range_pct"]   = (roll_high - roll_low) / df["close"]   # tighter = smaller

    # Volume surge ratio vs N-day average
    vol_avg = df["volume"].rolling(vol_look).mean().shift(1)
    f["vol_ratio"] = df["volume"] / vol_avg

    # Breakout signal: close > prior N-day high
    prior_high = df["high"].rolling(break_look).max().shift(1)
    f["prior_high"] = prior_high
    f["breakout"] = df["close"] > prior_high

    # Price above multiple MAs (trend filter)
    f["ma20"] = df["close"].rolling(20).mean()
    f["ma60"] = df["close"].rolling(60).mean()
    f["above_ma20"] = df["close"] > f["ma20"]
    f["above_ma60"] = df["close"] > f["ma60"]

    # Candle body strength (close near high = bullish candle)
    daily_range = (df["high"] - df["low"]).replace(0, np.nan)
    f["body_strength"] = (df["close"] - df["open"]) / daily_range

    return f

# ---------------------------------------------------------------------------
# Portfolio Backtest
# ---------------------------------------------------------------------------

class Trade(NamedTuple):
    ticker: str
    entry_date: object
    exit_date: object
    entry_price: float
    exit_price: float
    pnl_pct: float      # net of transaction costs


def run_backtest(
    signal_fn: Callable[[pd.DataFrame, dict], pd.Series],
    params: dict,
    universe: dict[str, pd.DataFrame],
    split: str = "in",
) -> tuple[pd.Series, list[Trade]]:
    """
    Optimised daily portfolio backtest.
    Pre-computes entry signals for all stocks before the simulation loop.

    Parameters
    ----------
    signal_fn : callable(features_df, params) -> pd.Series[bool]
        Entry signal function.  True means 'enter long on next open'.
    params : dict
        Strategy parameters forwarded to signal_fn and feature computation.
    universe : dict[str, pd.DataFrame]
        {ticker: ohlcv_df} from load_universe().
    split : 'in' | 'out'
        Which data partition to use.

    Returns
    -------
    equity : pd.Series   — daily portfolio value (starts at 1.0)
    trades : list[Trade] — all completed round-trip trades
    """
    # ── Date range ────────────────────────────────────────────────────────
    all_dates = sorted(set(d for df in universe.values() for d in df.index))
    all_dates = pd.DatetimeIndex(all_dates)
    if split == "in":
        mask = all_dates < pd.Timestamp(IN_SAMPLE_END)
    else:
        mask = all_dates >= pd.Timestamp(OUT_SAMPLE_START)
    dates = all_dates[mask]
    if len(dates) < 10:
        return pd.Series([1.0], dtype=float), []
    d0, d1 = dates[0], dates[-1]

    # ── Pre-compute features & signals (vectorised, before any loop) ───────
    signal_panel: dict[str, pd.Series] = {}
    atr_panel:    dict[str, pd.Series] = {}
    close_panel:  dict[str, pd.Series] = {}
    open_panel:   dict[str, pd.Series] = {}
    vol_panel:    dict[str, pd.Series] = {}

    for ticker, df in universe.items():
        try:
            feats = compute_features(df.loc[d0:d1], params)
            sig   = signal_fn(feats, params).fillna(False).astype(bool)
            signal_panel[ticker] = sig
            atr_panel[ticker]    = feats["atr"]
            close_panel[ticker]  = df.loc[d0:d1, "close"]
            open_panel[ticker]   = df.loc[d0:d1, "open"]
            vol_panel[ticker]    = df.loc[d0:d1, "volume"]
        except Exception:
            pass

    max_pos   = params.get("MAX_POSITIONS", 5)
    stop_atr  = params.get("STOP_LOSS_ATR", 2.5)
    trail_atr = params.get("TRAILING_STOP_ATR", 2.0)
    max_hold  = params.get("MAX_HOLD_DAYS", 30)
    min_price = params.get("MIN_PRICE", 10.0)
    min_vol   = params.get("MIN_VOLUME", 500)

    # ── Simulation loop ────────────────────────────────────────────────────
    cash      = 1.0
    positions: dict[str, dict] = {}
    equity_curve: list[float] = []
    trades: list[Trade] = []

    for i, date in enumerate(dates):
        # Exit open positions
        to_exit = []
        for ticker, pos in positions.items():
            cl = close_panel.get(ticker)
            if cl is None or date not in cl.index:
                continue
            price = cl.loc[date]
            pos["peak"] = max(pos["peak"], price)
            pos["days"] += 1
            stop = max(
                pos["entry_price"] - stop_atr  * pos["atr"],
                pos["peak"]        - trail_atr * pos["atr"],
            )
            if price <= stop or pos["days"] >= max_hold:
                to_exit.append((ticker, price))

        for ticker, exit_price in to_exit:
            pos      = positions.pop(ticker)
            proceeds = pos["shares"] * exit_price * (1 - COMMISSION_SELL - SEC_TAX)
            cash    += proceeds
            pnl_pct  = (proceeds - pos["cost_basis"]) / pos["cost_basis"]
            trades.append(Trade(ticker, pos["entry_date"], date,
                                pos["entry_price"], exit_price, pnl_pct))

        # Enter new positions (signal on date, execute on next open)
        if len(positions) < max_pos and i + 1 < len(dates):
            next_date  = dates[i + 1]
            candidates = []
            for ticker, sig in signal_panel.items():
                if ticker in positions:
                    continue
                if date not in sig.index or not sig.loc[date]:
                    continue
                cl = close_panel.get(ticker)
                vl = vol_panel.get(ticker)
                if cl is None or date not in cl.index:
                    continue
                if cl.loc[date] < min_price:
                    continue
                if vl is not None and date in vl.index and vl.loc[date] < min_vol:
                    continue
                at = atr_panel.get(ticker)
                atr_val = float(at.loc[date]) if (at is not None and date in at.index) else np.nan
                candidates.append((ticker, atr_val))

            slots = max_pos - len(positions)
            for ticker, atr_val in candidates[:slots]:
                op = open_panel.get(ticker)
                if op is None or next_date not in op.index:
                    continue
                entry_price = op.loc[next_date]
                if entry_price <= 0 or np.isnan(entry_price):
                    continue
                alloc      = 1.0 / max_pos
                cost_basis = cash * alloc
                if cost_basis <= 0:
                    continue
                shares  = cost_basis / (entry_price * (1 + COMMISSION_BUY))
                cash   -= cost_basis
                positions[ticker] = dict(
                    shares      = shares,
                    entry_price = entry_price,
                    entry_date  = next_date,
                    atr         = atr_val if not np.isnan(atr_val) else entry_price * 0.02,
                    peak        = entry_price,
                    days        = 0,
                    cost_basis  = cost_basis,
                )

        # Mark-to-market
        mtm = sum(
            pos["shares"] * close_panel[t].loc[date]
            for t, pos in positions.items()
            if t in close_panel and date in close_panel[t].index
        )
        equity_curve.append(cash + mtm)

    return pd.Series(equity_curve, index=dates, dtype=float), trades

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class BacktestResult(NamedTuple):
    composite:       float   # PRIMARY METRIC — maximize this
    sortino:         float
    max_drawdown:    float   # as decimal (0.5 = 50% drawdown)
    win_rate:        float
    profit_factor:   float
    num_trades:      int
    annual_return:   float


def compute_metrics(equity: pd.Series, trades: list[Trade]) -> BacktestResult:
    """Compute all performance metrics from equity curve + trade list."""
    if len(equity) < 2 or equity.iloc[0] == 0:
        return BacktestResult(
            composite=-99, sortino=-99, max_drawdown=1.0,
            win_rate=0, profit_factor=0, num_trades=0, annual_return=-1,
        )

    daily_ret = equity.pct_change().dropna()
    n_days    = len(daily_ret)

    # Annualised return
    total_ret   = equity.iloc[-1] / equity.iloc[0] - 1
    annual_ret  = (1 + total_ret) ** (TRADING_DAYS_PER_YEAR / max(n_days, 1)) - 1

    # Sortino ratio
    downside = daily_ret[daily_ret < SORTINO_MAR] - SORTINO_MAR
    down_std = float(downside.std()) if len(downside) > 1 else 1e-6
    if down_std < 1e-9:
        down_std = 1e-9
    mean_excess = float(daily_ret.mean()) - SORTINO_MAR
    sortino = (mean_excess / down_std) * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Maximum drawdown
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax
    max_dd = float(drawdown.min()) * -1   # positive value, 0.3 = 30% drawdown

    # Trade stats
    num_trades = len(trades)
    if num_trades > 0:
        wins   = [t.pnl_pct for t in trades if t.pnl_pct > 0]
        losses = [t.pnl_pct for t in trades if t.pnl_pct <= 0]
        win_rate = len(wins) / num_trades
        gross_win  = sum(wins)  if wins   else 0.0
        gross_loss = sum(abs(l) for l in losses) if losses else 1e-9
        profit_factor = gross_win / max(gross_loss, 1e-9)
    else:
        win_rate = 0.0
        profit_factor = 0.0

    composite = sortino * (1 - max_dd)

    return BacktestResult(
        composite    = round(composite, 6),
        sortino      = round(sortino, 6),
        max_drawdown = round(max_dd, 6),
        win_rate     = round(win_rate, 4),
        profit_factor= round(profit_factor, 4),
        num_trades   = num_trades,
        annual_return= round(annual_ret, 4),
    )


def evaluate(
    signal_fn: Callable,
    params: dict,
    universe: dict[str, pd.DataFrame] | None = None,
) -> tuple[BacktestResult, BacktestResult]:
    """
    Run full evaluation on both in-sample and out-of-sample splits.

    Returns
    -------
    (in_sample_result, out_sample_result) : tuple[BacktestResult, BacktestResult]
    """
    if universe is None:
        universe = load_universe()

    eq_in,  trades_in  = run_backtest(signal_fn, params, universe, split="in")
    eq_out, trades_out = run_backtest(signal_fn, params, universe, split="out")

    r_in  = compute_metrics(eq_in,  trades_in)
    r_out = compute_metrics(eq_out, trades_out)
    return r_in, r_out


def print_results(label: str, r: BacktestResult) -> None:
    """Pretty-print a BacktestResult."""
    print(
        f"[{label:10s}] "
        f"Composite: {r.composite:+.4f} | "
        f"Sortino: {r.sortino:+.3f} | "
        f"MDD: {r.max_drawdown*100:.1f}% | "
        f"Ann.Ret: {r.annual_return*100:.1f}% | "
        f"WinRate: {r.win_rate*100:.1f}% | "
        f"PF: {r.profit_factor:.2f} | "
        f"Trades: {r.num_trades}"
    )
