"""
Regime Terminal API — Railway service entry point.

Endpoints:
- GET /health — service status + candle counts
- GET /regimes — current regime state for all symbols
- GET /regimes/{symbol} — regime + candles for a specific symbol
- GET /split — train/test split boundary info
- GET /symbols — configured symbols
- POST /sync/{symbol} — trigger manual sync
"""
import os
import json
import math
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Regime Terminal", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

NEON_URI = os.environ.get("NEON_URI", os.environ.get("DATABASE_URL", ""))

def get_conn():
    import psycopg2
    return psycopg2.connect(NEON_URI)


@app.get("/health")
def health():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT symbol, COUNT(*) FROM candles GROUP BY symbol ORDER BY symbol")
        counts = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM candles")
        total = cur.fetchone()[0]
        cur.close(); conn.close()
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(), "total_candles": total, "symbols": counts}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/regimes")
def regimes():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ON (symbol) symbol, open_time, close, regime, confidence FROM candles ORDER BY symbol, open_time DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    names = ["Strong Bull", "Bull", "Weak Bull", "Neutral", "Weak Bear", "Bear", "Crash"]
    result = []
    for sym, ot, close, regime, conf in rows:
        result.append({"symbol": sym, "price": close, "regime": regime, "regime_name": names[regime] if regime is not None and 0 <= regime <= 6 else "Unknown", "confidence": conf, "last_update": datetime.fromtimestamp(ot / 1000, tz=timezone.utc).isoformat()})
    return {"regimes": result, "count": len(result)}


@app.get("/regimes/{symbol}")
def regime_detail(symbol: str, limit: int = 1440):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT open_time, open, high, low, close, volume, regime, confidence FROM candles WHERE symbol=%s AND interval='1m' ORDER BY open_time DESC LIMIT %s", (symbol.upper(), limit))
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    candles = [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5], "regime": r[6], "conf": r[7]} for r in reversed(rows)]
    return {"symbol": symbol.upper(), "candles": candles, "count": len(candles)}


@app.get("/split")
def split_info():
    from src.evaluate import SPLIT_MS, SPLIT_LABEL
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candles WHERE open_time < %s", (SPLIT_MS,))
    train = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM candles WHERE open_time >= %s", (SPLIT_MS,))
    test = cur.fetchone()[0]
    cur.close(); conn.close()
    return {"split_date": SPLIT_LABEL, "split_ms": SPLIT_MS, "train_candles": train, "test_candles": test}


@app.get("/symbols")
def symbols():
    with open("config/symbols.json") as f:
        return json.load(f)


@app.post("/sync/{symbol}")
def sync_symbol(symbol: str, days_back: int = 1):
    import httpx
    from io import StringIO
    import psycopg2
    from src.regime import classify
    symbol = symbol.upper()
    now = datetime.now(timezone.utc)
    start_ms = int((now - timedelta(days=days_back)).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1m&startTime={start_ms}&endTime={end_ms}&limit=1000"
    resp = httpx.get(url, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Binance API error")
    raw = resp.json()
    if not raw:
        return {"symbol": symbol, "fetched": 0}
    closes = [float(k[4]) for k in raw]
    volumes = [float(k[5]) for k in raw]
    buf = StringIO()
    for i, k in enumerate(raw):
        r, cf = classify(closes, volumes, i)
        buf.write(f"{symbol}\t1m\t{k[0]}\t{k[1]}\t{k[2]}\t{k[3]}\t{k[4]}\t{k[5]}\t{k[7]}\t{k[8]}\t{r}\t{round(cf, 3)}\t0\t0\t0\n")
    buf.seek(0)
    conn = psycopg2.connect(NEON_URI)
    cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE tmp (LIKE candles INCLUDING DEFAULTS) ON COMMIT DROP")
    cur.execute("ALTER TABLE tmp DROP COLUMN id, DROP COLUMN created_at")
    cur.copy_from(buf, 'tmp', columns=['symbol', 'interval', 'open_time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'regime', 'confidence', 'returns', 'volatility', 'volume_ratio'])
    cur.execute("""INSERT INTO candles (symbol, interval, open_time, open, high, low, close, volume, quote_volume, trades, regime, confidence, returns, volatility, volume_ratio)
        SELECT * FROM tmp ON CONFLICT (symbol, interval, open_time) DO NOTHING""")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM candles WHERE symbol=%s", (symbol,))
    total = cur.fetchone()[0]
    cur.close(); conn.close()
    return {"symbol": symbol, "fetched": len(raw), "total": total}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
