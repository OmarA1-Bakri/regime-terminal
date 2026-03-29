"""
MA-Based Seasonality Analysis

PHILOSOPHY: Only surface patterns where statistical evidence is strong.
If there's no real pattern, return nothing. No forced narratives.

Uses t-tests and effect size (Cohen's d) to filter out noise.
A pattern must pass BOTH significance AND effect size thresholds
to be considered real.

Thresholds:
- p-value < 0.05 (95% confidence)
- |Cohen's d| > 0.2 (small but meaningful effect size)
- Sample size >= 1000 (enough data to trust)
"""
import math
from collections import defaultdict
from src.db import get_candles, get_conn

P_THRESHOLD = 0.05
EFFECT_THRESHOLD = 0.2
MIN_SAMPLES = 1000


def t_test(sample, population_mean=0):
    n = len(sample)
    if n < 30:
        return 0, 1.0
    mean = sum(sample) / n
    var = sum((x - mean) ** 2 for x in sample) / (n - 1)
    if var == 0:
        return 0, 1.0
    se = math.sqrt(var / n)
    t_stat = (mean - population_mean) / se
    p = 2 * (1 - _norm_cdf(abs(t_stat)))
    return t_stat, p


def cohens_d(sample, population_mean=0):
    n = len(sample)
    if n < 2:
        return 0
    mean = sum(sample) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in sample) / (n - 1))
    if std == 0:
        return 0
    return (mean - population_mean) / std


def _norm_cdf(x):
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x) / math.sqrt(2)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)


def _rolling_ma(values, window):
    ma = [0.0] * len(values)
    running = 0
    for i in range(len(values)):
        running += values[i]
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            ma[i] = running / window
    return ma


def find_significant_patterns(symbol, interval="1m"):
    candles = get_candles(symbol, interval)
    if len(candles) < MIN_SAMPLES * 2:
        return {"symbol": symbol, "patterns": [], "patterns_found": 0, "message": "Insufficient data"}

    returns = []
    for i in range(1, len(candles)):
        if candles[i - 1][4] > 0:
            returns.append({"ret": (candles[i][4] - candles[i - 1][4]) / candles[i - 1][4], "open_time": candles[i][0]})

    if not returns:
        return {"symbol": symbol, "patterns": [], "patterns_found": 0, "message": "No returns"}

    all_rets = [r["ret"] for r in returns]
    global_mean = sum(all_rets) / len(all_rets)
    import datetime as dt
    patterns = []

    # Monthly
    monthly = defaultdict(list)
    for r in returns:
        ts = dt.datetime.fromtimestamp(r["open_time"] / 1000, tz=dt.timezone.utc)
        monthly[ts.month].append(r["ret"])
    month_names = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for month, rets in monthly.items():
        if len(rets) < MIN_SAMPLES: continue
        t_stat, p_val = t_test(rets, global_mean)
        d = cohens_d(rets, global_mean)
        if p_val < P_THRESHOLD and abs(d) > EFFECT_THRESHOLD:
            avg = sum(rets) / len(rets)
            patterns.append({"type": "monthly", "period": month_names[month], "avg_return": avg, "vs_global": avg - global_mean, "direction": "bullish" if avg > global_mean else "bearish", "p_value": round(p_val, 6), "cohens_d": round(d, 3), "effect_size": "large" if abs(d) > 0.8 else "medium" if abs(d) > 0.5 else "small", "sample_size": len(rets), "confidence": "high" if p_val < 0.01 else "moderate"})

    # Hourly
    hourly = defaultdict(list)
    for r in returns:
        ts = dt.datetime.fromtimestamp(r["open_time"] / 1000, tz=dt.timezone.utc)
        hourly[ts.hour].append(r["ret"])
    for hour, rets in hourly.items():
        if len(rets) < MIN_SAMPLES: continue
        t_stat, p_val = t_test(rets, global_mean)
        d = cohens_d(rets, global_mean)
        if p_val < P_THRESHOLD and abs(d) > EFFECT_THRESHOLD:
            avg = sum(rets) / len(rets)
            patterns.append({"type": "hourly", "period": f"{hour:02d}:00 UTC", "avg_return": avg, "vs_global": avg - global_mean, "direction": "bullish" if avg > global_mean else "bearish", "p_value": round(p_val, 6), "cohens_d": round(d, 3), "effect_size": "large" if abs(d) > 0.8 else "medium" if abs(d) > 0.5 else "small", "sample_size": len(rets), "confidence": "high" if p_val < 0.01 else "moderate"})

    # Day of week
    daily = defaultdict(list)
    for r in returns:
        ts = dt.datetime.fromtimestamp(r["open_time"] / 1000, tz=dt.timezone.utc)
        daily[ts.weekday()].append(r["ret"])
    day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    for dow, rets in daily.items():
        if len(rets) < MIN_SAMPLES: continue
        t_stat, p_val = t_test(rets, global_mean)
        d = cohens_d(rets, global_mean)
        if p_val < P_THRESHOLD and abs(d) > EFFECT_THRESHOLD:
            avg = sum(rets) / len(rets)
            patterns.append({"type": "day_of_week", "period": day_names[dow], "avg_return": avg, "vs_global": avg - global_mean, "direction": "bullish" if avg > global_mean else "bearish", "p_value": round(p_val, 6), "cohens_d": round(d, 3), "effect_size": "large" if abs(d) > 0.8 else "medium" if abs(d) > 0.5 else "small", "sample_size": len(rets), "confidence": "high" if p_val < 0.01 else "moderate"})

    # MA crossover: 50/200 SMA
    closes = [c[4] for c in candles]
    if len(closes) > 200:
        ma50 = _rolling_ma(closes, 50)
        ma200 = _rolling_ma(closes, 200)
        above_rets, below_rets = [], []
        for i in range(201, len(closes)):
            if closes[i - 1] > 0:
                ret = (closes[i] - closes[i - 1]) / closes[i - 1]
                if ma50[i] > ma200[i]: above_rets.append(ret)
                else: below_rets.append(ret)
        for label, rets in [("50/200 SMA \u2014 above (golden)", above_rets), ("50/200 SMA \u2014 below (death)", below_rets)]:
            if len(rets) >= MIN_SAMPLES:
                t_stat, p_val = t_test(rets, global_mean)
                d = cohens_d(rets, global_mean)
                if p_val < P_THRESHOLD and abs(d) > EFFECT_THRESHOLD:
                    avg = sum(rets) / len(rets)
                    patterns.append({"type": "ma_cross", "period": label, "avg_return": avg, "vs_global": avg - global_mean, "direction": "bullish" if avg > global_mean else "bearish", "p_value": round(p_val, 6), "cohens_d": round(d, 3), "effect_size": "large" if abs(d) > 0.8 else "medium" if abs(d) > 0.5 else "small", "sample_size": len(rets), "confidence": "high" if p_val < 0.01 else "moderate"})

    patterns.sort(key=lambda p: abs(p["cohens_d"]), reverse=True)
    return {"symbol": symbol, "total_candles": len(candles), "global_mean_return": global_mean, "patterns_found": len(patterns), "patterns": patterns, "message": f"{len(patterns)} significant patterns" if patterns else "No statistically significant patterns detected"}


def scan_all_symbols(symbols, interval="1m"):
    results = {}
    for sym in symbols:
        analysis = find_significant_patterns(sym, interval)
        if analysis["patterns_found"] > 0:
            results[sym] = analysis
    return results


if __name__ == "__main__":
    import json
    with open("config/symbols.json") as f:
        symbols = json.load(f)["all"]
    results = scan_all_symbols(symbols)
    if not results:
        print("No statistically significant seasonal patterns found across any symbol.")
    else:
        for sym, data in results.items():
            print(f"\n{'='*50}")
            print(f"{sym}: {data['patterns_found']} significant patterns")
            for p in data["patterns"]:
                d = "\u2191" if p["direction"] == "bullish" else "\u2193"
                print(f"  {d} {p['type']:12s} | {p['period']:25s} | d={p['cohens_d']:+.3f} ({p['effect_size']}) | p={p['p_value']:.6f} | n={p['sample_size']:,}")
