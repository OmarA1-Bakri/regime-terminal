"""
ATR (Average True Range) Module

Computes ATR for any symbol on any timeframe from Neon PostgreSQL.
Used for dynamic stop losses and position sizing.

ATR = average of True Range over N periods
True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
"""
import os


def compute_atr(highs, lows, closes, period=14):
    """
    Compute ATR from price arrays.
    Returns list of ATR values (None for first `period` values).
    """
    if len(closes) < period + 1:
        return [None] * len(closes)
    
    true_ranges = [None]  # first candle has no previous close
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)
    
    # Initial ATR = simple average of first `period` true ranges
    atrs = [None] * period
    valid_trs = [tr for tr in true_ranges[1:period + 1] if tr is not None]
    if not valid_trs:
        return [None] * len(closes)
    
    atr = sum(valid_trs) / len(valid_trs)
    atrs.append(atr)
    
    # Smoothed ATR (Wilder's method)
    for i in range(period + 1, len(closes)):
        tr = true_ranges[i]
        if tr is not None:
            atr = (atr * (period - 1) + tr) / period
        atrs.append(atr)
    
    return atrs


def get_current_atr(symbol, timeframe="4h", period=14, neon_uri=None):
    """
    Get current ATR value for a symbol from Neon.
    Returns dict with atr, atr_pct (as % of price), and stop distances by tier.
    """
    import psycopg2
    if neon_uri is None:
        neon_uri = os.environ.get("NEON_URI", "")
    
    table = {"1m": "candles", "1h": "candles_1h", "4h": "candles_4h"}.get(timeframe, "candles_4h")
    
    conn = psycopg2.connect(neon_uri)
    cur = conn.cursor()
    cur.execute(f"SELECT close, high, low FROM {table} WHERE symbol=%s ORDER BY open_time DESC LIMIT %s", (symbol, period + 5))
    rows = list(reversed(cur.fetchall()))
    cur.close(); conn.close()
    
    if len(rows) < period + 1:
        return {"error": f"Not enough data: {len(rows)} candles, need {period + 1}"}
    
    closes = [float(r[0]) for r in rows]
    highs = [float(r[1]) for r in rows]
    lows = [float(r[2]) for r in rows]
    
    atrs = compute_atr(highs, lows, closes, period)
    current_atr = atrs[-1]
    current_price = closes[-1]
    
    if current_atr is None:
        return {"error": "Could not compute ATR"}
    
    atr_pct = (current_atr / current_price) * 100
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "period": period,
        "atr": round(current_atr, 6),
        "atr_pct": round(atr_pct, 3),
        "current_price": current_price,
        "stops": {
            "tier1_long": round(current_price - 2.0 * current_atr, 6),
            "tier1_short": round(current_price + 2.0 * current_atr, 6),
            "tier2_long": round(current_price - 2.5 * current_atr, 6),
            "tier2_short": round(current_price + 2.5 * current_atr, 6),
            "tier3_long": round(current_price - 3.0 * current_atr, 6),
            "tier3_short": round(current_price + 3.0 * current_atr, 6),
            "leveraged_long": round(current_price - 1.5 * current_atr, 6),
            "leveraged_short": round(current_price + 1.5 * current_atr, 6),
        },
        "trailing": {
            "breakeven_trigger": round(current_price + 1.0 * current_atr, 6),
            "trail_2x_trigger": round(current_price + 2.0 * current_atr, 6),
            "trail_tight_trigger": round(current_price + 3.0 * current_atr, 6),
        }
    }


def get_atr_all_symbols(timeframe="4h", period=14, neon_uri=None):
    """Get ATR for all symbols in one call."""
    import psycopg2, json
    if neon_uri is None:
        neon_uri = os.environ.get("NEON_URI", "")
    
    try:
        with open("config/symbols.json") as f:
            syms_data = json.load(f)
        symbols = [s["symbol"] for s in syms_data.get("symbols", syms_data)] if isinstance(syms_data, dict) else [s["symbol"] for s in syms_data]
    except Exception:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "BNBUSDT"]
    
    results = {}
    for sym in symbols:
        results[sym] = get_current_atr(sym, timeframe, period, neon_uri)
    return results
