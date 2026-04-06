"""
Alpaca Paper Trading Client
============================
Handles all interaction with Alpaca's paper trading API v2.
Supports: account info, positions, orders, market data, and trade execution.

Environment variables:
    ALPACA_API_KEY    - Alpaca API Key ID
    ALPACA_API_SECRET - Alpaca API Secret Key
"""
import os
import time
import httpx
from datetime import datetime, timezone

BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
DATA_URL = "https://data.alpaca.markets"

API_KEY = os.getenv("ALPACA_API_KEY", "PKWY36S4PNQFCQDTWSFHNTVARA")
API_SECRET = os.getenv("ALPACA_API_SECRET", "A8uY6N5fahU5k32z26ZLoy9ViwXKNkqBLb29kMLm9ZfC")


def _headers():
    return {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET,
        "accept": "application/json",
    }


def _get(url, params=None, base=None):
    r = httpx.get((base or BASE_URL) + url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(url, json_body=None):
    r = httpx.post(BASE_URL + url, headers=_headers(), json=json_body, timeout=30)
    r.raise_for_status()
    return r.json()


def _delete(url):
    r = httpx.delete(BASE_URL + url, headers=_headers(), timeout=30)
    if r.status_code == 204:
        return {}
    r.raise_for_status()
    return r.json()


# ── Account ──────────────────────────────────────────────────────────

def get_account():
    """Get account details: equity, buying power, cash, etc."""
    return _get("/v2/account")


def get_buying_power():
    acct = get_account()
    return float(acct["buying_power"])


def get_equity():
    acct = get_account()
    return float(acct["equity"])


def get_cash():
    acct = get_account()
    return float(acct["cash"])


# ── Positions ────────────────────────────────────────────────────────

def get_positions():
    """Get all open positions."""
    return _get("/v2/positions")


def get_position(symbol):
    """Get position for a specific symbol."""
    try:
        return _get(f"/v2/positions/{symbol}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


def close_position(symbol, qty=None, percentage=None):
    """Close a position. Optionally specify qty or percentage."""
    params = {}
    if qty:
        params["qty"] = str(qty)
    elif percentage:
        params["percentage"] = str(percentage)
    r = httpx.delete(
        BASE_URL + f"/v2/positions/{symbol}",
        headers=_headers(), params=params, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def close_all_positions():
    """Liquidate all positions."""
    return _delete("/v2/positions")


# ── Orders ───────────────────────────────────────────────────────────

def place_order(symbol, qty, side, order_type="market", time_in_force="day",
                limit_price=None, stop_price=None, trail_percent=None):
    """
    Place an order on Alpaca.

    Args:
        symbol: Ticker symbol (e.g., "AAPL")
        qty: Number of shares (can be fractional)
        side: "buy" or "sell"
        order_type: "market", "limit", "stop", "stop_limit", "trailing_stop"
        time_in_force: "day", "gtc", "ioc", "fok"
        limit_price: Required for limit/stop_limit orders
        stop_price: Required for stop/stop_limit orders
        trail_percent: Required for trailing_stop orders
    """
    body = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if limit_price is not None:
        body["limit_price"] = str(limit_price)
    if stop_price is not None:
        body["stop_price"] = str(stop_price)
    if trail_percent is not None:
        body["trail_percent"] = str(trail_percent)
    return _post("/v2/orders", body)


def place_bracket_order(symbol, qty, side, take_profit_price, stop_loss_price,
                        time_in_force="gtc"):
    """Place a bracket order with take-profit and stop-loss legs."""
    body = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": "market",
        "time_in_force": time_in_force,
        "order_class": "bracket",
        "take_profit": {"limit_price": str(take_profit_price)},
        "stop_loss": {"stop_price": str(stop_loss_price)},
    }
    return _post("/v2/orders", body)


def get_orders(status="open", limit=50):
    """Get orders. Status: open, closed, all."""
    return _get("/v2/orders", params={"status": status, "limit": limit})


def cancel_all_orders():
    """Cancel all open orders."""
    return _delete("/v2/orders")


# ── Market Data ──────────────────────────────────────────────────────

def get_bars(symbol, timeframe="1Day", start=None, end=None, limit=200):
    """
    Get historical bars from Alpaca Data API.

    Args:
        symbol: Ticker symbol
        timeframe: "1Min", "5Min", "15Min", "1Hour", "1Day", "1Week"
        start: RFC3339 date string (e.g., "2025-01-01")
        end: RFC3339 date string
        limit: Max bars to return (max 10000)
    """
    params = {"timeframe": timeframe, "limit": limit}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return _get(f"/v2/stocks/{symbol}/bars", params=params, base=DATA_URL)


def get_bars_multi(symbols, timeframe="1Day", start=None, end=None, limit=200):
    """Get bars for multiple symbols at once."""
    params = {
        "symbols": ",".join(symbols),
        "timeframe": timeframe,
        "limit": limit,
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return _get("/v2/stocks/bars", params=params, base=DATA_URL)


def get_latest_quote(symbol):
    """Get the latest quote for a symbol."""
    return _get(f"/v2/stocks/{symbol}/quotes/latest", base=DATA_URL)


def get_latest_trade(symbol):
    """Get the latest trade for a symbol."""
    return _get(f"/v2/stocks/{symbol}/trades/latest", base=DATA_URL)


def get_snapshot(symbol):
    """Get snapshot (latest trade, quote, minute/daily bar) for a symbol."""
    return _get(f"/v2/stocks/{symbol}/snapshot", base=DATA_URL)


def get_snapshots(symbols):
    """Get snapshots for multiple symbols."""
    return _get("/v2/stocks/snapshots", params={"symbols": ",".join(symbols)}, base=DATA_URL)


# ── Clock & Calendar ─────────────────────────────────────────────────

def get_clock():
    """Get market clock: is_open, next_open, next_close."""
    return _get("/v2/clock")


def is_market_open():
    return get_clock()["is_open"]


# ── Portfolio History ────────────────────────────────────────────────

def get_portfolio_history(period="1M", timeframe="1D"):
    """Get portfolio equity history."""
    return _get("/v2/account/portfolio/history",
                params={"period": period, "timeframe": timeframe})


# ── Convenience ──────────────────────────────────────────────────────

def buy(symbol, qty, order_type="market", **kwargs):
    """Shorthand for a buy order."""
    return place_order(symbol, qty, "buy", order_type, **kwargs)


def sell(symbol, qty, order_type="market", **kwargs):
    """Shorthand for a sell order."""
    return place_order(symbol, qty, "sell", order_type, **kwargs)


def portfolio_summary():
    """Human-readable portfolio summary."""
    acct = get_account()
    positions = get_positions()
    summary = {
        "equity": float(acct["equity"]),
        "cash": float(acct["cash"]),
        "buying_power": float(acct["buying_power"]),
        "pnl_today": float(acct.get("equity", 0)) - float(acct.get("last_equity", 0)),
        "positions": [],
    }
    for p in positions:
        summary["positions"].append({
            "symbol": p["symbol"],
            "qty": float(p["qty"]),
            "side": p["side"],
            "entry": float(p["avg_entry_price"]),
            "current": float(p["current_price"]),
            "pnl": float(p["unrealized_pl"]),
            "pnl_pct": float(p["unrealized_plpc"]) * 100,
            "market_value": float(p["market_value"]),
        })
    return summary
