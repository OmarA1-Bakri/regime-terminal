"""
Data fetcher for Binance public API (no auth required).
Fetches historical klines and caches locally as CSV for fast re-use.
"""
import os
import time
import json
import csv
from pathlib import Path
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    httpx = None

CACHE_DIR = Path(__file__).parent.parent / "data_cache"
BINANCE_BASE = "https://api.binance.us"


def _fetch_klines_batch(symbol, interval, start_ms, end_ms, limit=1000):
    """Fetch a single batch of klines from Binance."""
    if httpx is None:
        raise ImportError("httpx required: pip install httpx")
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": int(start_ms),
        "endTime": int(end_ms),
        "limit": limit,
    }
    r = httpx.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_klines(symbol, interval="4h", start_date="2024-03-01", end_date="2026-03-31"):
    """
    Fetch all klines for a symbol between dates. Uses local cache.
    Returns list of [open_time, open, high, low, close, volume].
    """
    cache_file = CACHE_DIR / f"{symbol}_{interval}_{start_date}_{end_date}.csv"
    if cache_file.exists():
        return _load_cache(cache_file)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    interval_ms = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    }
    step = interval_ms.get(interval, 14_400_000) * 999

    all_candles = []
    cursor = start_ms
    while cursor < end_ms:
        batch_end = min(cursor + step, end_ms)
        retries = 0
        batch = None
        while retries < 3:
            try:
                batch = _fetch_klines_batch(symbol, interval, cursor, batch_end)
                break
            except Exception as e:
                retries += 1
                print(f"  Error fetching {symbol} at {cursor} (attempt {retries}): {e}")
                time.sleep(2)
        if batch is None:
            cursor = batch_end
            continue
        if not batch:
            break
        for k in batch:
            all_candles.append([
                int(k[0]),       # open_time
                float(k[1]),     # open
                float(k[2]),     # high
                float(k[3]),     # low
                float(k[4]),     # close
                float(k[5]),     # volume
            ])
        cursor = int(batch[-1][0]) + interval_ms.get(interval, 14_400_000)
        time.sleep(0.15)  # rate limit respect

    # Deduplicate by open_time
    seen = set()
    unique = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    unique.sort(key=lambda x: x[0])

    _save_cache(cache_file, unique)
    return unique


def _save_cache(path, candles):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume"])
        w.writerows(candles)


def _load_cache(path):
    candles = []
    with open(path, "r") as f:
        r = csv.reader(f)
        next(r)  # skip header
        for row in r:
            candles.append([int(row[0]), float(row[1]), float(row[2]),
                           float(row[3]), float(row[4]), float(row[5])])
    return candles


def fetch_all_symbols(symbols, interval="4h", start_date="2024-03-01", end_date="2026-03-31"):
    """Fetch data for all symbols. Returns dict {symbol: candles}."""
    data = {}
    for sym in symbols:
        print(f"  Fetching {sym}...")
        candles = fetch_klines(sym, interval, start_date, end_date)
        if candles:
            data[sym] = candles
            print(f"    -> {len(candles)} candles")
        else:
            print(f"    -> NO DATA")
    return data
