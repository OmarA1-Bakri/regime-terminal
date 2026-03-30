"""
IMMUTABLE BACKTESTER — The agent CANNOT modify this file.
This is the 'prepare.py' equivalent from Karpathy's autoresearch.

CRITICAL: Enforces train/test split.
- TRAIN: Mar 2024 → Jul 31 2025 (~16 months) — agent optimizes on this
- TEST:  Aug 1 2025 → Mar 2026 (~8 months)  — forward-looking holdout

The agent's keep/discard decision is based on TRAIN Sharpe only.
TEST results are reported separately to detect overfitting.
The agent MUST NOT use TEST data to make optimization decisions.

Metrics (ranked by priority):
1. Sharpe Ratio (primary — the val_bpb equivalent)
2. Total Return %
3. Max Drawdown
4. Win Rate
"""
import math
import json
from src.db import get_candles
from src.regime import classify

# ─── SPLIT BOUNDARY (DO NOT CHANGE) ───
# Aug 1, 2025 00:00:00 UTC in milliseconds
SPLIT_MS = 1753833600000
SPLIT_LABEL = "2025-08-01"


def _run_backtest(strategy_fn, candles, initial_capital=10000):
    """Core backtest engine. Runs strategy against a candle array."""
    if len(candles) < 100:
        return None

    closes = [c[4] for c in candles]
    volumes = [c[5] for c in candles]
    equity = initial_capital
    peak = equity
    max_dd = 0
    trades = []
    position = None
    state = {}

    for i, candle in enumerate(candles):
        regime, confidence = classify(closes, volumes, i)
        signal = strategy_fn(candle, regime, confidence, state)

        if signal.get("action") == "ENTER" and position is None:
            position = {
                "entry_price": candle[4],
                "side": signal.get("side", "LONG"),
                "leverage": signal.get("leverage", 1.0),
                "entry_idx": i,
            }
        elif signal.get("action") == "EXIT" and position is not None:
            exit_price = candle[4]
            entry_price = position["entry_price"]
            if position["side"] == "LONG":
                pnl_pct = (exit_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - exit_price) / entry_price
            pnl_pct *= position["leverage"]
            equity *= 1 + pnl_pct
            trades.append({"pnl_pct": pnl_pct, "bars": i - position["entry_idx"]})
            position = None

        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    total_return = (equity - initial_capital) / initial_capital * 100
    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    win_rate = (wins / len(trades) * 100) if trades else 0
    avg_return = sum(t["pnl_pct"] for t in trades) / len(trades) if trades else 0
    std_return = (
        math.sqrt(sum((t["pnl_pct"] - avg_return) ** 2 for t in trades) / len(trades))
        if len(trades) > 1
        else 1
    )
    sharpe = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0

    return {
        "sharpe": round(sharpe, 3),
        "total_return": round(total_return, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "win_rate": round(win_rate, 1),
        "trades": len(trades),
        "final_equity": round(equity, 2),
    }


def _aggregate(results):
    """Aggregate per-symbol results into summary metrics."""
    if not results:
        return {"sharpe": 0, "total_return": 0, "max_drawdown": 100, "win_rate": 0, "trades": 0, "symbols": {}}
    avg_sharpe = sum(r["sharpe"] for r in results.values()) / len(results)
    avg_return = sum(r["total_return"] for r in results.values()) / len(results)
    worst_dd = max(r["max_drawdown"] for r in results.values())
    avg_win = sum(r["win_rate"] for r in results.values()) / len(results)
    total_trades = sum(r["trades"] for r in results.values())
    return {
        "sharpe": round(avg_sharpe, 3),
        "total_return": round(avg_return, 2),
        "max_drawdown": round(worst_dd, 2),
        "win_rate": round(avg_win, 1),
        "trades": total_trades,
        "symbols": results,
    }


def backtest(strategy_fn, symbols, interval="1m", initial_capital=10000):
    """Run strategy on TRAIN data only (pre-split)."""
    results = {}
    for symbol in symbols:
        candles = get_candles(symbol, interval, end_time=SPLIT_MS)
        result = _run_backtest(strategy_fn, candles, initial_capital)
        if result:
            results[symbol] = result
    return _aggregate(results)


def forward_test(strategy_fn, symbols, interval="1m", initial_capital=10000):
    """Run strategy on TEST data only (post-split). HOLDOUT for overfit detection."""
    results = {}
    for symbol in symbols:
        candles = get_candles(symbol, interval, start_time=SPLIT_MS)
        result = _run_backtest(strategy_fn, candles, initial_capital)
        if result:
            results[symbol] = result
    return _aggregate(results)


def full_report(strategy_fn, symbols, interval="1m", initial_capital=10000):
    """Complete report: train + test + overfit detection. For human review."""
    train = backtest(strategy_fn, symbols, interval, initial_capital)
    test = forward_test(strategy_fn, symbols, interval, initial_capital)

    sharpe_decay = 0
    if train["sharpe"] != 0:
        sharpe_decay = (train["sharpe"] - test["sharpe"]) / abs(train["sharpe"]) * 100

    return {
        "split_date": SPLIT_LABEL,
        "train": train,
        "test": test,
        "overfit_metrics": {
            "sharpe_decay_pct": round(sharpe_decay, 1),
            "return_decay_pct": round(
                (train["total_return"] - test["total_return"]) / abs(train["total_return"]) * 100
                if train["total_return"] != 0 else 0, 1
            ),
            "drawdown_increase_pct": round(test["max_drawdown"] - train["max_drawdown"], 1),
            "likely_overfit": sharpe_decay > 50 or test["sharpe"] < 0,
        },
    }


def score(metrics):
    """Single scalar score for keep/discard decision. Higher is better."""
    return metrics["sharpe"]


if __name__ == "__main__":
    from src.strategy import strategy_fn

    with open("config/symbols.json") as f:
        symbols = json.load(f)["all"]

    print(f"Split date: {SPLIT_LABEL}")
    print(f"{'='*60}")

    report = full_report(strategy_fn, symbols)

    print(f"\n--- TRAIN (Mar 2024 -> Jul 2025) ---")
    print(json.dumps(report["train"], indent=2))

    print(f"\n--- FORWARD TEST (Aug 2025 -> Mar 2026) ---")
    print(json.dumps(report["test"], indent=2))

    print(f"\n--- OVERFIT DETECTION ---")
    om = report["overfit_metrics"]
    print(f"  Sharpe decay:     {om['sharpe_decay_pct']:+.1f}%")
    print(f"  Return decay:     {om['return_decay_pct']:+.1f}%")
    print(f"  Drawdown change:  {om['drawdown_increase_pct']:+.1f}%")
    print(f"  Likely overfit:   {'YES' if om['likely_overfit'] else 'NO'}")

    print(f"\nTRAIN SCORE (Sharpe): {score(report['train'])}")
