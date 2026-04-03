"""
Volume Profile / Point of Control Analysis

Computes volume profile, POC, Value Area (VAH/VAL) from candle data.
Designed to complement the HMM regime classifier:
- HMM tells you WHAT state the market is in (Bull, Bear, etc.)
- Volume Profile tells you WHERE in the price structure you are

Key concepts:
- POC (Point of Control): price level with highest traded volume
- VAH (Value Area High): upper bound of 70% volume range
- VAL (Value Area Low): lower bound of 70% volume range
- HVN (High Volume Node): price clusters with heavy trading (support/resistance)
- LVN (Low Volume Node): thin volume zones (breakout/breakdown areas)

Usage:
  from src.volume_profile import compute_profile, get_poc_analysis
  profile = compute_profile(closes, volumes, highs, lows, num_buckets=50)
  analysis = get_poc_analysis(symbol, timeframe="4h", lookback=100)
"""
import os
import math
from collections import defaultdict


def compute_profile(closes, highs, lows, volumes, num_buckets=50, value_area_pct=0.70):
    """
    Compute volume profile from OHLCV data.
    
    Args:
        closes: list of close prices
        highs: list of high prices
        lows: list of low prices  
        volumes: list of volumes
        num_buckets: number of price levels to divide range into
        value_area_pct: percentage of volume for value area (default 70%)
    
    Returns:
        dict with poc, vah, val, profile (list of {price, volume}), 
        hvn (high volume nodes), lvn (low volume nodes)
    """
    if not closes or len(closes) < 2:
        return None
    
    price_min = min(lows)
    price_max = max(highs)
    
    if price_max == price_min:
        return None
    
    bucket_size = (price_max - price_min) / num_buckets
    if bucket_size == 0:
        return None
    
    # Build volume profile: distribute each candle's volume across its price range
    profile = defaultdict(float)
    
    for i in range(len(closes)):
        candle_low = lows[i]
        candle_high = highs[i]
        candle_vol = volumes[i]
        
        if candle_high == candle_low:
            # Doji: all volume at one price
            bucket = int((candle_low - price_min) / bucket_size)
            bucket = min(bucket, num_buckets - 1)
            profile[bucket] += candle_vol
        else:
            # Distribute volume proportionally across price range
            low_bucket = int((candle_low - price_min) / bucket_size)
            high_bucket = int((candle_high - price_min) / bucket_size)
            low_bucket = max(0, min(low_bucket, num_buckets - 1))
            high_bucket = max(0, min(high_bucket, num_buckets - 1))
            
            n_buckets_touched = high_bucket - low_bucket + 1
            vol_per_bucket = candle_vol / n_buckets_touched if n_buckets_touched > 0 else candle_vol
            
            for b in range(low_bucket, high_bucket + 1):
                profile[b] += vol_per_bucket
    
    # Convert to sorted list
    profile_list = []
    for b in range(num_buckets):
        price_level = price_min + (b + 0.5) * bucket_size
        vol = profile.get(b, 0)
        profile_list.append({"price": round(price_level, 6), "volume": round(vol, 2), "bucket": b})
    
    # Find POC (bucket with highest volume)
    poc_bucket = max(profile_list, key=lambda x: x["volume"])
    poc_price = poc_bucket["price"]
    
    # Compute Value Area (70% of total volume centered on POC)
    total_volume = sum(p["volume"] for p in profile_list)
    target_volume = total_volume * value_area_pct
    
    # Expand outward from POC
    poc_idx = poc_bucket["bucket"]
    included = {poc_idx}
    accumulated = profile.get(poc_idx, 0)
    lower = poc_idx - 1
    upper = poc_idx + 1
    
    while accumulated < target_volume and (lower >= 0 or upper < num_buckets):
        vol_lower = profile.get(lower, 0) if lower >= 0 else 0
        vol_upper = profile.get(upper, 0) if upper < num_buckets else 0
        
        if vol_lower >= vol_upper and lower >= 0:
            accumulated += vol_lower
            included.add(lower)
            lower -= 1
        elif upper < num_buckets:
            accumulated += vol_upper
            included.add(upper)
            upper += 1
        else:
            break
    
    val_bucket = min(included)
    vah_bucket = max(included)
    val_price = price_min + (val_bucket + 0.5) * bucket_size
    vah_price = price_min + (vah_bucket + 0.5) * bucket_size
    
    # Identify High Volume Nodes and Low Volume Nodes
    avg_vol = total_volume / num_buckets if num_buckets > 0 else 0
    hvn_threshold = avg_vol * 1.5
    lvn_threshold = avg_vol * 0.5
    
    hvn = [p for p in profile_list if p["volume"] > hvn_threshold]
    lvn = [p for p in profile_list if 0 < p["volume"] < lvn_threshold]
    
    return {
        "poc": round(poc_price, 6),
        "poc_volume": round(poc_bucket["volume"], 2),
        "vah": round(vah_price, 6),
        "val": round(val_price, 6),
        "value_area_pct": value_area_pct,
        "value_area_volume_pct": round(accumulated / total_volume * 100, 1) if total_volume > 0 else 0,
        "price_range": {"min": round(price_min, 6), "max": round(price_max, 6)},
        "bucket_size": round(bucket_size, 6),
        "total_volume": round(total_volume, 2),
        "profile": profile_list,
        "hvn": [{"price": h["price"], "volume": h["volume"]} for h in sorted(hvn, key=lambda x: x["volume"], reverse=True)[:10]],
        "lvn": [{"price": l["price"], "volume": l["volume"]} for l in sorted(lvn, key=lambda x: x["volume"])[:10]],
    }


def analyse_price_vs_profile(current_price, profile_result):
    """
    Analyse current price position relative to volume profile.
    
    Returns signals for trading decisions:
    - Position relative to POC (above/below/at)
    - Position relative to Value Area (inside/above/below)
    - Nearest support/resistance (HVN levels)
    - Nearest breakout zones (LVN levels)
    """
    if not profile_result:
        return None
    
    poc = profile_result["poc"]
    vah = profile_result["vah"]
    val = profile_result["val"]
    
    # Price vs POC
    poc_distance_pct = ((current_price - poc) / poc) * 100 if poc > 0 else 0
    
    if abs(poc_distance_pct) < 0.3:
        poc_position = "AT_POC"
    elif current_price > poc:
        poc_position = "ABOVE_POC"
    else:
        poc_position = "BELOW_POC"
    
    # Price vs Value Area
    if current_price > vah:
        va_position = "ABOVE_VALUE_AREA"
        va_signal = "Breakout territory - price above where 70% of volume traded. Could extend or reject back."
    elif current_price < val:
        va_position = "BELOW_VALUE_AREA"
        va_signal = "Breakdown territory - price below where 70% of volume traded. Could find support or continue falling."
    else:
        va_position = "INSIDE_VALUE_AREA"
        va_signal = "Fair value zone - price within the range where most volume traded. Likely to consolidate."
    
    # Nearest HVN (support/resistance)
    nearest_hvn_above = None
    nearest_hvn_below = None
    for hvn in profile_result.get("hvn", []):
        if hvn["price"] > current_price:
            if nearest_hvn_above is None or hvn["price"] < nearest_hvn_above["price"]:
                nearest_hvn_above = hvn
        elif hvn["price"] < current_price:
            if nearest_hvn_below is None or hvn["price"] > nearest_hvn_below["price"]:
                nearest_hvn_below = hvn
    
    # Nearest LVN (breakout/breakdown zones)
    nearest_lvn_above = None
    nearest_lvn_below = None
    for lvn in profile_result.get("lvn", []):
        if lvn["price"] > current_price:
            if nearest_lvn_above is None or lvn["price"] < nearest_lvn_above["price"]:
                nearest_lvn_above = lvn
        elif lvn["price"] < current_price:
            if nearest_lvn_below is None or lvn["price"] > nearest_lvn_below["price"]:
                nearest_lvn_below = lvn
    
    return {
        "current_price": current_price,
        "poc": poc,
        "poc_position": poc_position,
        "poc_distance_pct": round(poc_distance_pct, 2),
        "vah": vah,
        "val": val,
        "va_position": va_position,
        "va_signal": va_signal,
        "nearest_resistance": nearest_hvn_above,
        "nearest_support": nearest_hvn_below,
        "nearest_lvn_above": nearest_lvn_above,
        "nearest_lvn_below": nearest_lvn_below,
    }


def detect_poc_shift(profiles_over_time):
    """
    Detect POC shift over multiple periods.
    Rising POC = institutional accumulation (bullish)
    Falling POC = institutional distribution (bearish)
    Stable POC = equilibrium
    
    Args:
        profiles_over_time: list of profile results ordered chronologically
    
    Returns:
        dict with shift direction and magnitude
    """
    if len(profiles_over_time) < 2:
        return {"shift": "INSUFFICIENT_DATA", "periods": len(profiles_over_time)}
    
    pocs = [p["poc"] for p in profiles_over_time if p and "poc" in p]
    if len(pocs) < 2:
        return {"shift": "INSUFFICIENT_DATA", "periods": len(pocs)}
    
    first_poc = pocs[0]
    last_poc = pocs[-1]
    shift_pct = ((last_poc - first_poc) / first_poc) * 100 if first_poc > 0 else 0
    
    # Check consistency of direction
    up_moves = sum(1 for i in range(1, len(pocs)) if pocs[i] > pocs[i-1])
    down_moves = sum(1 for i in range(1, len(pocs)) if pocs[i] < pocs[i-1])
    consistency = max(up_moves, down_moves) / (len(pocs) - 1) if len(pocs) > 1 else 0
    
    if abs(shift_pct) < 0.5:
        direction = "STABLE"
        signal = "POC stable - market in equilibrium. Wait for breakout."
    elif shift_pct > 0:
        direction = "RISING"
        signal = f"POC shifted up {shift_pct:.1f}% over {len(pocs)} periods. Institutional accumulation - bullish."
    else:
        direction = "FALLING"
        signal = f"POC shifted down {abs(shift_pct):.1f}% over {len(pocs)} periods. Institutional distribution - bearish."
    
    return {
        "shift": direction,
        "shift_pct": round(shift_pct, 2),
        "consistency": round(consistency, 2),
        "periods": len(pocs),
        "first_poc": first_poc,
        "last_poc": last_poc,
        "signal": signal,
    }


def get_profile_from_db(symbol, timeframe="4h", lookback=100, num_buckets=50, neon_uri=None):
    """
    Compute volume profile from Neon database.
    
    Args:
        symbol: e.g. BTCUSDT
        timeframe: 1m, 1h, or 4h
        lookback: number of candles to use
        num_buckets: price level granularity
        neon_uri: database connection string
    """
    import psycopg2
    if neon_uri is None:
        neon_uri = os.environ.get("NEON_URI", "")
    
    table = {"1m": "candles", "1h": "candles_1h", "4h": "candles_4h"}.get(timeframe, "candles_4h")
    
    conn = psycopg2.connect(neon_uri)
    cur = conn.cursor()
    cur.execute(f"SELECT close, high, low, volume FROM {table} WHERE symbol=%s ORDER BY open_time DESC LIMIT %s", (symbol, lookback))
    rows = list(reversed(cur.fetchall()))
    cur.close(); conn.close()
    
    if len(rows) < 10:
        return None
    
    closes = [float(r[0]) for r in rows]
    highs = [float(r[1]) for r in rows]
    lows = [float(r[2]) for r in rows]
    volumes = [float(r[3]) for r in rows]
    
    return compute_profile(closes, highs, lows, volumes, num_buckets)


def get_poc_analysis(symbol, timeframe="4h", lookback=100, neon_uri=None):
    """
    Full POC analysis for a symbol: profile + price position + POC shift.
    This is the main function Claude calls for trading decisions.
    """
    import psycopg2
    if neon_uri is None:
        neon_uri = os.environ.get("NEON_URI", "")
    
    table = {"1m": "candles", "1h": "candles_1h", "4h": "candles_4h"}.get(timeframe, "candles_4h")
    
    conn = psycopg2.connect(neon_uri)
    cur = conn.cursor()
    
    # Get candles for profile
    cur.execute(f"SELECT close, high, low, volume FROM {table} WHERE symbol=%s ORDER BY open_time DESC LIMIT %s", (symbol, lookback))
    rows = list(reversed(cur.fetchall()))
    
    if len(rows) < 10:
        cur.close(); conn.close()
        return {"error": f"Not enough {timeframe} data for {symbol}: {len(rows)} candles"}
    
    closes = [float(r[0]) for r in rows]
    highs = [float(r[1]) for r in rows]
    lows = [float(r[2]) for r in rows]
    volumes = [float(r[3]) for r in rows]
    current_price = closes[-1]
    
    # Current profile
    profile = compute_profile(closes, highs, lows, volumes)
    if not profile:
        cur.close(); conn.close()
        return {"error": "Could not compute profile"}
    
    # Price analysis
    price_analysis = analyse_price_vs_profile(current_price, profile)
    
    # POC shift: compute profiles for 5 rolling windows
    window = lookback // 5
    rolling_profiles = []
    for i in range(5):
        start = i * window
        end = start + window
        if end <= len(closes):
            p = compute_profile(
                closes[start:end], highs[start:end],
                lows[start:end], volumes[start:end]
            )
            if p:
                rolling_profiles.append(p)
    
    poc_shift = detect_poc_shift(rolling_profiles)
    
    cur.close(); conn.close()
    
    # Strip full profile data for the summary (too large for API response)
    profile_summary = {
        "poc": profile["poc"],
        "vah": profile["vah"],
        "val": profile["val"],
        "total_volume": profile["total_volume"],
        "hvn": profile["hvn"][:5],
        "lvn": profile["lvn"][:5],
    }
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "lookback": lookback,
        "current_price": current_price,
        "profile_summary": profile_summary,
        "price_analysis": price_analysis,
        "poc_shift": poc_shift,
    }
