"""
Regime Terminal API — Railway service entry point.

Endpoints:
- GET /health
- GET /regimes, /regimes/{symbol}
- GET /split, /symbols
- POST /sync/{symbol}
- GET /testnet/portfolio, /testnet/balance/{asset}, /testnet/trades
- POST /testnet/execute/{symbol}
- GET /portfolio, /portfolio/pnl, /portfolio/allocations, /portfolio/history
- POST /portfolio/open, /portfolio/close/{position_id}
- PUT /portfolio/allocations/{strategy}
"""
import os
import json
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Regime Terminal", version="2.0.0")

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


# ========== REQUEST MODELS ==========

class OpenPositionRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_price: float
    strategy: str = "regime"
    regime: Optional[int] = None
    confidence: Optional[float] = None
    notes: Optional[str] = None
    execute: bool = True

class ClosePositionRequest(BaseModel):
    exit_price: float
    notes: Optional[str] = None
    execute: bool = True

class UpdateAllocationRequest(BaseModel):
    target_pct: Optional[float] = None
    max_position_pct: Optional[float] = None
    max_positions: Optional[int] = None
    enabled: Optional[bool] = None


# ========== REGIME ENDPOINTS ==========

@app.get("/health")
def health():
    try:
        conn = get_conn(); cur = conn.cursor()
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
    conn = get_conn(); cur = conn.cursor()
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
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT open_time, open, high, low, close, volume, regime, confidence FROM candles WHERE symbol=%s AND interval='1m' ORDER BY open_time DESC LIMIT %s", (symbol.upper(), limit))
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    candles = [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5], "regime": r[6], "conf": r[7]} for r in reversed(rows)]
    return {"symbol": symbol.upper(), "candles": candles, "count": len(candles)}


@app.get("/split")
def split_info():
    SPLIT_MS = 1753833600000
    SPLIT_LABEL = "2025-08-01"
    conn = get_conn(); cur = conn.cursor()
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
    import math
    closes = [float(k[4]) for k in raw]
    volumes = [float(k[5]) for k in raw]
    buf = StringIO()
    w = 14
    for i, k in enumerate(raw):
        r, cf = 3, 0.5
        if i >= w:
            rets = [(closes[j]-closes[j-1])/closes[j-1] for j in range(max(1,i-w+1),i+1) if closes[j-1]>0]
            if rets:
                ar = sum(rets)/len(rets)
                vo = math.sqrt(sum((x-ar)**2 for x in rets)/len(rets)) if len(rets)>1 else 0
                av = sum(volumes[max(0,i-w):i+1])/min(w+1,i+1)
                vr = volumes[i]/av if av>0 else 1
                sc = ar*10000
                if vo>0.03: sc-=2
                if vr>2: sc+=1 if sc>0 else -1
                if sc>3: r,cf=0,min(.95,.6+sc*.03)
                elif sc>1.5: r,cf=1,min(.97,.55+sc*.05)
                elif sc>.3: r,cf=2,min(.97,.5+sc*.08)
                elif sc>-.3: r,cf=3,min(.97,.4+abs(sc)*.1)
                elif sc>-1.5: r,cf=4,min(.97,.5+abs(sc)*.08)
                elif sc>-3: r,cf=5,min(.97,.55+abs(sc)*.05)
                else: r,cf=6,min(.95,.6+abs(sc)*.03)
        buf.write(f"{symbol}\t1m\t{k[0]}\t{k[1]}\t{k[2]}\t{k[3]}\t{k[4]}\t{k[5]}\t{k[7]}\t{k[8]}\t{r}\t{round(cf,3)}\t0\t0\t0\n")
    buf.seek(0)
    conn = psycopg2.connect(NEON_URI); cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE tmp (LIKE candles INCLUDING DEFAULTS) ON COMMIT DROP")
    cur.execute("ALTER TABLE tmp DROP COLUMN id, DROP COLUMN created_at")
    cur.copy_from(buf, 'tmp', columns=['symbol','interval','open_time','open','high','low','close','volume','quote_volume','trades','regime','confidence','returns','volatility','volume_ratio'])
    cur.execute("""INSERT INTO candles (symbol,interval,open_time,open,high,low,close,volume,quote_volume,trades,regime,confidence,returns,volatility,volume_ratio)
        SELECT * FROM tmp ON CONFLICT (symbol,interval,open_time) DO NOTHING""")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM candles WHERE symbol=%s", (symbol,))
    total = cur.fetchone()[0]
    cur.close(); conn.close()
    return {"symbol": symbol, "fetched": len(raw), "total": total}


# ========== TESTNET PAPER TRADING ENDPOINTS ==========

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

@app.get("/testnet/price/{symbol}")
def testnet_price(symbol: str):
    from src.paper_trade import get_price
    return {"symbol": symbol.upper(), "price": get_price(symbol.upper())}


# ========== PORTFOLIO MANAGEMENT ENDPOINTS ==========

@app.get("/portfolio")
def portfolio():
    from src.portfolio import get_book
    positions = get_book()
    return {"positions": positions, "count": len(positions)}


@app.post("/portfolio/open")
def portfolio_open(req: OpenPositionRequest):
    from src.portfolio import open_position
    result = open_position(
        symbol=req.symbol, side=req.side, quantity=req.quantity,
        entry_price=req.entry_price, strategy=req.strategy,
        regime=req.regime, confidence=req.confidence,
        notes=req.notes, execute=req.execute
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/portfolio/close/{position_id}")
def portfolio_close(position_id: int, req: ClosePositionRequest):
    from src.portfolio import close_position
    result = close_position(
        position_id=position_id, exit_price=req.exit_price,
        notes=req.notes, execute=req.execute
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/portfolio/pnl")
def portfolio_pnl(strategy: Optional[str] = None):
    from src.portfolio import get_pnl
    return get_pnl(strategy)


@app.get("/portfolio/allocations")
def portfolio_allocations():
    from src.portfolio import get_allocations
    return {"allocations": get_allocations()}


@app.put("/portfolio/allocations/{strategy}")
def portfolio_update_allocation(strategy: str, req: UpdateAllocationRequest):
    from src.portfolio import update_allocation
    result = update_allocation(
        strategy=strategy, target_pct=req.target_pct,
        max_position_pct=req.max_position_pct,
        max_positions=req.max_positions, enabled=req.enabled
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/portfolio/history")
def portfolio_history(limit: int = 50, strategy: Optional[str] = None):
    from src.portfolio import get_trade_history
    trades = get_trade_history(limit=limit, strategy=strategy)
    return {"trades": trades, "count": len(trades)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
