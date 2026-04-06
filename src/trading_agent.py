"""
Autonomous Trading Agent
=========================
Claude-powered trading loop that:
1. Fetches market data from Alpaca (stocks) + Neon (crypto)
2. Computes multi-factor signals across all symbols
3. Forms trade theses with reasoning
4. Validates through dual-layer system
5. Executes via exchange router
6. Manages portfolio risk in real-time

Run: python -m src.trading_agent
Interval: Every 15 minutes during market hours (configurable)
"""
import os
import sys
import json
import time
import math
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators import ema, sma, rsi, bollinger_bands, atr, donchian_channel, macd, adx
from src.multi_factor_strategy import SignalEngine, compute_position_size, DEFAULT_CONFIG
from src.exchange_router import execute_order, execute_bracket, get_portfolio, is_crypto

try:
    import httpx
except ImportError:
    httpx = None

# ── Configuration ────────────────────────────────────────────────────

LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", "900"))  # 15 min default
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RAILWAY_URL = os.getenv("RAILWAY_URL",
    "https://regime-terminal-production-b43b.up.railway.app")

# Combined universe
STOCK_SYMBOLS = [
    "NVDA", "TSLA", "AMD", "PLTR", "SOFI",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "QQQ", "SPY", "COIN", "MSTR",
]

CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "RENDERUSDT",
    "FETUSDT", "NEARUSDT", "ARUSDT", "INJUSDT", "SUIUSDT", "PENDLEUSDT",
]

CONVICTION_THRESHOLD = 0.30  # minimum conviction to trade
MAX_POSITIONS = 5
MAX_PORTFOLIO_RISK = 0.10  # 10% total at risk


# ── Data Fetchers ────────────────────────────────────────────────────

def fetch_stock_bars(symbol, days=120):
    """Fetch daily bars from Alpaca Data API."""
    from src import alpaca_client
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        resp = alpaca_client.get_bars(symbol, timeframe="1Day", start=start, limit=days)
        bars = resp.get("bars", [])
        candles = []
        for b in bars:
            candles.append([
                int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() * 1000),
                float(b["o"]),
                float(b["h"]),
                float(b["l"]),
                float(b["c"]),
                float(b["v"]),
            ])
        return candles
    except Exception as e:
        print(f"  [WARN] Failed to fetch {symbol}: {e}")
        return []


def fetch_crypto_bars(symbol, days=120):
    """Fetch daily bars from Railway API (Neon data)."""
    try:
        r = httpx.get(f"{RAILWAY_URL}/regimes/{symbol}",
                      params={"limit": days * 24 * 60}, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
        # Aggregate 1m candles to daily
        daily = {}
        for c in data.get("candles", []):
            day_key = c["open_time"] // 86400000
            if day_key not in daily:
                daily[day_key] = {
                    "t": day_key * 86400000,
                    "o": c["open"], "h": c["high"],
                    "l": c["low"], "c": c["close"], "v": c["volume"],
                }
            else:
                d = daily[day_key]
                d["h"] = max(d["h"], c["high"])
                d["l"] = min(d["l"], c["low"])
                d["c"] = c["close"]
                d["v"] += c["volume"]
        candles = []
        for d in sorted(daily.values(), key=lambda x: x["t"]):
            candles.append([d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]])
        return candles
    except Exception as e:
        print(f"  [WARN] Failed to fetch crypto {symbol}: {e}")
        return []


def fetch_regime_data(symbol):
    """Get HMM regime classification from Railway API."""
    try:
        r = httpx.get(f"{RAILWAY_URL}/regimes/multi/{symbol}", timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_volume_profile(symbol):
    """Get Volume Profile analysis from Railway API."""
    try:
        r = httpx.get(f"{RAILWAY_URL}/volume-profile/{symbol}/analysis", timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── Claude Risk Assessment ───────────────────────────────────────────

def claude_assess_trade(trade_thesis, market_context, portfolio_state):
    """
    Ask Claude to evaluate a trade thesis.
    Returns: {"decision": "APPROVE"|"REJECT", "reasoning": str, "confidence": float}
    """
    if not ANTHROPIC_API_KEY:
        # Fallback: mechanical approval based on conviction
        return {
            "decision": "APPROVE" if abs(trade_thesis.get("conviction", 0)) > 0.4 else "REJECT",
            "reasoning": "No API key — using mechanical threshold",
            "confidence": abs(trade_thesis.get("conviction", 0)),
        }

    prompt = f"""You are a risk manager for an autonomous trading system.
Evaluate this trade thesis and decide APPROVE or REJECT.

TRADE THESIS:
{json.dumps(trade_thesis, indent=2)}

MARKET CONTEXT:
{json.dumps(market_context, indent=2)}

PORTFOLIO STATE:
{json.dumps(portfolio_state, indent=2)}

RULES:
- Reject if thesis contradicts the regime or volume profile
- Reject if portfolio is already heavily exposed to correlated assets
- Reject if timing is poor (news events, low liquidity hours)
- Reject if conviction < 0.3 or factors disagree
- Approve if multi-factor consensus, proper sizing, and clear thesis

Respond with JSON only:
{{"decision": "APPROVE" or "REJECT", "reasoning": "...", "confidence": 0.0-1.0, "adjustments": {{}}}}"""

    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if r.status_code == 200:
            text = r.json()["content"][0]["text"]
            # Extract JSON from response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
    except Exception as e:
        print(f"  [WARN] Claude risk assessment failed: {e}")

    return {"decision": "APPROVE", "reasoning": "API fallback", "confidence": 0.5}


# ── Core Trading Logic ───────────────────────────────────────────────

def analyze_symbol(symbol, candles, engine):
    """Analyze a single symbol and return trade signal if any."""
    if len(candles) < 60:
        return None

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    volumes = [c[5] for c in candles]

    signals = engine.compute_signals(closes, highs, lows, volumes)
    latest = signals[-1]

    if latest["regime"] == "warmup":
        return None

    conv = latest["conviction"]
    if abs(conv) < CONVICTION_THRESHOLD:
        return None

    # Build thesis
    bullish_factors = [k for k, v in latest["factors"].items() if v > 0.1]
    bearish_factors = [k for k, v in latest["factors"].items() if v < -0.1]
    side = "long" if conv > 0 else "short"

    return {
        "symbol": symbol,
        "side": side,
        "conviction": conv,
        "regime": latest["regime"],
        "factors": latest["factors"],
        "supporting": bullish_factors if side == "long" else bearish_factors,
        "opposing": bearish_factors if side == "long" else bullish_factors,
        "atr_val": latest["atr_val"],
        "stop_price": latest["stop_price"],
        "target_price": latest["target_price"],
        "current_price": closes[-1],
        "is_crypto": is_crypto(symbol),
    }


def run_analysis_cycle():
    """
    Single analysis cycle:
    1. Fetch data for all symbols
    2. Compute signals
    3. Rank candidates
    4. Validate top picks
    5. Execute approved trades
    """
    engine = SignalEngine()
    candidates = []
    skipped = 0

    print(f"\n{'=' * 60}")
    print(f"  ANALYSIS CYCLE — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'=' * 60}")

    # ── Fetch & Analyze Stocks ──
    print("\n  [STOCKS]")
    for sym in STOCK_SYMBOLS:
        candles = fetch_stock_bars(sym)
        if not candles:
            skipped += 1
            continue
        signal = analyze_symbol(sym, candles, engine)
        if signal:
            candidates.append(signal)
            print(f"    {sym:8s} {signal['side']:5s} conv={signal['conviction']:+.2f} "
                  f"regime={signal['regime']} factors={len(signal['supporting'])}+"
                  f"/{len(signal['opposing'])}-")

    # ── Fetch & Analyze Crypto ──
    print("\n  [CRYPTO]")
    for sym in CRYPTO_SYMBOLS:
        candles = fetch_crypto_bars(sym)
        if not candles:
            skipped += 1
            continue
        signal = analyze_symbol(sym, candles, engine)
        if signal:
            # Enrich with HMM regime data if available
            regime_data = fetch_regime_data(sym)
            if regime_data:
                signal["hmm_regime"] = regime_data
            vp_data = fetch_volume_profile(sym)
            if vp_data:
                signal["volume_profile"] = vp_data
            candidates.append(signal)
            print(f"    {sym:12s} {signal['side']:5s} conv={signal['conviction']:+.2f} "
                  f"regime={signal['regime']}")

    print(f"\n  Scanned: {len(STOCK_SYMBOLS) + len(CRYPTO_SYMBOLS)} symbols")
    print(f"  Skipped: {skipped}, Signals: {len(candidates)}")

    if not candidates:
        print("  No actionable signals. Sitting tight.")
        return []

    # ── Rank by absolute conviction ──
    candidates.sort(key=lambda x: abs(x["conviction"]), reverse=True)

    # ── Get portfolio state ──
    portfolio = get_portfolio()
    total_positions = sum(len(p) for p in portfolio.values())
    available_slots = MAX_POSITIONS - total_positions

    if available_slots <= 0:
        print(f"  Portfolio full ({total_positions}/{MAX_POSITIONS} positions). "
              f"Managing existing only.")
        return []

    # ── Validate & Execute top candidates ──
    executed = []
    for signal in candidates[:available_slots]:
        print(f"\n  Evaluating: {signal['symbol']} {signal['side']} "
              f"(conv={signal['conviction']:+.3f})")

        # Claude risk assessment
        assessment = claude_assess_trade(
            trade_thesis=signal,
            market_context={
                "total_candidates": len(candidates),
                "market_regime": "mixed",
            },
            portfolio_state={
                "positions": total_positions,
                "max_positions": MAX_POSITIONS,
            },
        )

        if assessment["decision"] == "REJECT":
            print(f"    REJECTED: {assessment['reasoning']}")
            continue

        # Position sizing
        equity = 100_000  # default paper account
        try:
            from src import alpaca_client
            equity = alpaca_client.get_equity()
        except Exception:
            pass

        qty = compute_position_size(
            equity, signal["conviction"], signal["atr_val"],
            signal["current_price"])

        if qty < 1:
            print(f"    SKIP: position size too small (qty={qty})")
            continue

        # Execute
        side = "buy" if signal["side"] == "long" else "sell"
        print(f"    APPROVED: {side} {qty} {signal['symbol']} "
              f"@ ~${signal['current_price']:.2f}")
        print(f"    Stop: ${signal['stop_price']:.2f}  "
              f"Target: ${signal['target_price']:.2f}")
        print(f"    Reasoning: {assessment['reasoning']}")

        result = execute_order(
            symbol=signal["symbol"], side=side, qty=qty, dry_run=DRY_RUN)
        print(f"    Execution: {result['status']} on {result['exchange']}")

        executed.append({
            "signal": signal,
            "assessment": assessment,
            "execution": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return executed


# ── Portfolio Management ─────────────────────────────────────────────

def check_exits():
    """Check existing positions for exit signals."""
    portfolio = get_portfolio()
    exits = []

    for exchange, positions in portfolio.items():
        for sym, pos in positions.items():
            pnl_pct = pos.get("pnl_pct", 0)

            # Hard stop: -5% unrealized
            if pnl_pct < -5:
                print(f"  EXIT SIGNAL: {sym} at {pnl_pct:+.1f}% (hard stop)")
                exits.append({"symbol": sym, "reason": "hard_stop", "exchange": exchange})

            # Take profit: +10% unrealized
            elif pnl_pct > 10:
                print(f"  EXIT SIGNAL: {sym} at {pnl_pct:+.1f}% (take profit)")
                exits.append({"symbol": sym, "reason": "take_profit", "exchange": exchange})

    for exit_sig in exits:
        sym = exit_sig["symbol"]
        if DRY_RUN:
            print(f"    DRY RUN: Would close {sym}")
        else:
            try:
                if exit_sig["exchange"] == "alpaca":
                    from src import alpaca_client
                    alpaca_client.close_position(sym)
                    print(f"    CLOSED {sym} on Alpaca")
                elif exit_sig["exchange"] == "binance":
                    from src import paper_trade
                    paper_trade.execute_signal(sym, {"action": "EXIT"})
                    print(f"    CLOSED {sym} on Binance")
            except Exception as e:
                print(f"    ERROR closing {sym}: {e}")

    return exits


# ── Main Loop ────────────────────────────────────────────────────────

def run_once():
    """Run a single trading cycle."""
    print(f"\n{'#' * 60}")
    print(f"  TRADING AGENT — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print(f"{'#' * 60}")

    # Check exits first
    exits = check_exits()

    # Then look for new entries
    executed = run_analysis_cycle()

    # Summary
    print(f"\n  {'─' * 40}")
    print(f"  Cycle complete: {len(exits)} exits, {len(executed)} entries")
    return {"exits": exits, "entries": executed}


def run_loop():
    """Continuous trading loop."""
    print("Starting autonomous trading agent...")
    print(f"Interval: {LOOP_INTERVAL}s | DRY_RUN: {DRY_RUN}")
    print(f"Stocks: {len(STOCK_SYMBOLS)} | Crypto: {len(CRYPTO_SYMBOLS)}")

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            print("\nShutting down gracefully...")
            break
        except Exception as e:
            print(f"\n  [ERROR] Cycle failed: {e}")
            traceback.print_exc()

        print(f"\n  Sleeping {LOOP_INTERVAL}s until next cycle...")
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_loop()
