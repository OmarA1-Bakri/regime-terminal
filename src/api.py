"""
Regime Terminal API v3.0.0 — Multi-Timeframe HMM + Volume Profile + ATR

Trains 1m, 1h, 4h HMMs at startup.
Volume Profile / POC analysis for price structure context.
ATR-based dynamic stop losses.
"""
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NEON_URI = os.environ.get("NEON_URI", os.environ.get("DATABASE_URL", ""))

def get_conn():
    import psycopg2
    return psycopg2.connect(NEON_URI)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Regime Terminal...")
    try:
        from src.regime import train_all_timeframes
        logger.info("Training HMMs on all timeframes...")
        results = train_all_timeframes(symbol="BTCUSDT", neon_uri=NEON_URI)
        for tf, r in results.items():
            if "error" in r:
                logger.warning(f"  {tf}: FAILED - {r['error']}")
            else:
                logger.info(f"  {tf}: {r['candles_used']} candles, converged={r.get('converged')}")
    except Exception as e:
        logger.warning(f"HMM training failed: {e}. Deterministic fallback.")
    yield
    logger.info("Shutting down.")


app = FastAPI(title="Regime Terminal", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT symbol, COUNT(*) FROM candles GROUP BY symbol ORDER BY symbol")
        counts = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM candles")
        total = cur.fetchone()[0]
        cur.close(); conn.close()
        from pathlib import Path
        models = {tf: Path(f"models/hmm_regime_{tf}.pkl").exists() for tf in ["1m", "1h", "4h"]}
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_candles": total, "symbols": counts, "hmm_models": models}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ========== REGIME ==========

@app.get("/regimes")
def regimes(timeframe: str = "4h"):
    from src.regime import classify, load_model, REGIMES
    try:
        model, scaler, state_map = load_model(timeframe)
    except Exception:
        model, scaler, state_map = None, None, None
    conn = get_conn(); cur = conn.cursor()
    table = {"1m": "candles", "1h": "candles_1h", "4h": "candles_4h"}.get(timeframe, "candles_4h")
    cur.execute(f"SELECT DISTINCT ON (symbol) symbol, open_time, close FROM {table} ORDER BY symbol, open_time DESC")
    symbols = cur.fetchall()
    result = []
    for sym, ot, close_price in symbols:
        cur.execute(f"SELECT close, volume FROM {table} WHERE symbol=%s ORDER BY open_time DESC LIMIT 50", (sym,))
        rows = list(reversed(cur.fetchall()))
        closes = [float(r[0]) for r in rows]
        volumes = [float(r[1]) for r in rows]
        regime, confidence = classify(closes, volumes, len(rows)-1, model=model, scaler=scaler, state_map=state_map, timeframe=timeframe)
        result.append({"symbol": sym, "price": close_price, "regime": regime,
                       "regime_name": REGIMES[regime]["name"], "confidence": confidence,
                       "last_update": datetime.fromtimestamp(ot / 1000, tz=timezone.utc).isoformat()})
    cur.close(); conn.close()
    return {"timeframe": timeframe, "regimes": result, "count": len(result)}


@app.get("/regimes/multi/{symbol}")
def regime_multi(symbol: str):
    from src.regime import classify_all_timeframes
    return {"symbol": symbol.upper(), "timeframes": classify_all_timeframes(symbol.upper(), NEON_URI)}


@app.get("/regimes/transitions")
def regime_transitions(timeframe: str = "4h"):
    try:
        from src.regime import get_transition_matrix
        return get_transition_matrix(timeframe=timeframe)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/regimes/states")
def regime_states(timeframe: str = "4h"):
    try:
        from src.regime import get_state_characteristics
        return get_state_characteristics(timeframe=timeframe)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/regimes/{symbol}")
def regime_detail(symbol: str, limit: int = 1440):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT open_time, open, high, low, close, volume, regime, confidence FROM candles WHERE symbol=%s AND interval='1m' ORDER BY open_time DESC LIMIT %s", (symbol.upper(), limit))
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    candles = [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5], "regime": r[6], "conf": r[7]} for r in reversed(rows)]
    return {"symbol": symbol.upper(), "candles": candles, "count": len(candles)}


@app.post("/train")
def train_model(symbol: str = "BTCUSDT", timeframe: str = "all"):
    from src.regime import train_from_db, train_all_timeframes
    if timeframe == "all":
        return train_all_timeframes(symbol=symbol, neon_uri=NEON_URI)
    return train_from_db(symbol=symbol, neon_uri=NEON_URI, timeframe=timeframe)


# ========== VOLUME PROFILE ==========

@app.get("/volume-profile/{symbol}")
def volume_profile(symbol: str, timeframe: str = "4h", lookback: int = 100, buckets: int = 50):
    from src.volume_profile import get_profile_from_db
    profile = get_profile_from_db(symbol.upper(), timeframe, lookback, buckets, NEON_URI)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")
    return {"symbol": symbol.upper(), "timeframe": timeframe, "lookback": lookback, "profile": profile}


@app.get("/volume-profile/{symbol}/poc")
def volume_profile_poc(symbol: str, timeframe: str = "4h", lookback: int = 100):
    from src.volume_profile import get_profile_from_db
    profile = get_profile_from_db(symbol.upper(), timeframe, lookback, neon_uri=NEON_URI)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")
    return {"symbol": symbol.upper(), "timeframe": timeframe,
            "poc": profile["poc"], "vah": profile["vah"], "val": profile["val"],
            "total_volume": profile["total_volume"], "hvn": profile["hvn"][:5], "lvn": profile["lvn"][:5]}


@app.get("/volume-profile/{symbol}/analysis")
def volume_profile_analysis(symbol: str, timeframe: str = "4h", lookback: int = 100):
    from src.volume_profile import get_poc_analysis
    result = get_poc_analysis(symbol.upper(), timeframe, lookback, NEON_URI)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ========== ATR ==========

@app.get("/atr/{symbol}")
def atr_endpoint(symbol: str, timeframe: str = "4h", period: int = 14):
    """ATR with stop loss levels for all tiers."""
    from src.atr import get_current_atr
    result = get_current_atr(symbol.upper(), timeframe, period, NEON_URI)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/atr")
def atr_all(timeframe: str = "4h", period: int = 14):
    """ATR for all symbols."""
    from src.atr import get_atr_all_symbols
    return get_atr_all_symbols(timeframe, period, NEON_URI)


# ========== UTILITY ==========

@app.get("/split")
def split_info():
    SPLIT_MS = 1753833600000
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candles WHERE open_time < %s", (SPLIT_MS,))
    train_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM candles WHERE open_time >= %s", (SPLIT_MS,))
    test_count = cur.fetchone()[0]
    cur.close(); conn.close()
    return {"split_date": "2025-08-01", "split_ms": SPLIT_MS, "train_candles": train_count, "test_candles": test_count}


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
    closes = [float(k[4]) for k in raw]; volumes = [float(k[5]) for k in raw]
    buf = StringIO()
    for i, k in enumerate(raw):
        r, cf = classify(closes, volumes, i)
        buf.write(f"{symbol}\t1m\t{k[0]}\t{k[1]}\t{k[2]}\t{k[3]}\t{k[4]}\t{k[5]}\t{k[7]}\t{k[8]}\t{r}\t{round(cf, 3)}\t0\t0\t0\n")
    buf.seek(0)
    conn = psycopg2.connect(NEON_URI); cur = conn.cursor()
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


# ========== PORTFOLIO ==========

class OpenPositionRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_price: float
    strategy: str
    regime: Optional[int] = None
    confidence: Optional[float] = None
    thesis: Optional[str] = ""
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

class ClosePositionRequest(BaseModel):
    exit_price: float
    reason: Optional[str] = ""

@app.get("/portfolio")
def portfolio():
    from src.portfolio import get_book
    return get_book()

@app.post("/portfolio/open")
def portfolio_open(req: OpenPositionRequest):
    from src.portfolio import open_position
    return open_position(symbol=req.symbol, side=req.side, quantity=req.quantity,
                         entry_price=req.entry_price, strategy=req.strategy,
                         regime=req.regime, confidence=req.confidence, thesis=req.thesis,
                         stop_loss=req.stop_loss, take_profit=req.take_profit)

@app.post("/portfolio/close/{position_id}")
def portfolio_close(position_id: int, req: ClosePositionRequest):
    from src.portfolio import close_position
    return close_position(position_id, req.exit_price, req.reason)

@app.get("/portfolio/pnl")
def portfolio_pnl():
    from src.portfolio import get_pnl
    return get_pnl()

@app.get("/portfolio/allocations")
def portfolio_allocations():
    from src.portfolio import get_allocations
    return get_allocations()

@app.get("/portfolio/history")
def portfolio_history(limit: int = 50):
    from src.portfolio import get_trade_history
    return get_trade_history(limit)


# ========== TESTNET ==========

@app.get("/testnet/portfolio")
def testnet_portfolio():
    from src.paper_trade import get_portfolio_summary
    return get_portfolio_summary()

@app.get("/testnet/balance/{asset}")
def testnet_balance(asset: str):
    from src.paper_trade import get_balance
    return get_balance(asset.upper())

@app.get("/testnet/trades")
def testnet_trades():
    from src.paper_trade import get_trade_log
    return {"trades": get_trade_log(), "count": len(get_trade_log())}

@app.post("/testnet/execute/{symbol}")
def testnet_execute(symbol: str):
    from src.paper_trade import execute_signal
    from src.regime import classify, load_model
    symbol = symbol.upper()
    try:
        model, scaler, state_map = load_model("4h")
    except Exception:
        model, scaler, state_map = None, None, None
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT close, volume FROM candles_4h WHERE symbol=%s ORDER BY open_time DESC LIMIT 50", (symbol,))
    rows = list(reversed(cur.fetchall()))
    cur.close(); conn.close()
    if len(rows) < 15:
        raise HTTPException(status_code=400, detail=f"Not enough data for {symbol}")
    closes = [float(r[0]) for r in rows]; volumes = [float(r[1]) for r in rows]
    regime, confidence = classify(closes, volumes, len(rows)-1, model=model, scaler=scaler, state_map=state_map, timeframe="4h")
    signal = {"action": "ENTER", "side": "LONG"} if regime <= 2 else {"action": "HOLD"}
    result = execute_signal(symbol, signal) if signal.get("action") == "ENTER" else None
    return {"symbol": symbol, "regime": regime, "confidence": confidence, "signal": signal, "execution": result}

@app.get("/testnet/price/{symbol}")
def testnet_price(symbol: str):
    from src.paper_trade import get_price
    return {"symbol": symbol.upper(), "price": get_price(symbol.upper())}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
