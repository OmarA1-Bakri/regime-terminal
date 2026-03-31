"""
Binance Testnet Paper Trading

Connects to Binance Spot Testnet to execute regime-based signals
with fake money. Same API as production, different base URL and keys.

Setup:
1. Go to https://testnet.binance.vision
2. Log in with GitHub
3. Generate API Key + Secret
4. Set env vars: BINANCE_TESTNET_KEY, BINANCE_TESTNET_SECRET

Modes:
- DRY_RUN=true (default): Logs signals, no orders placed
- DRY_RUN=false: Places real orders on testnet (fake money)
"""
import os
import time
import json
import hmac
import hashlib
import math
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from src.regime import classify

TESTNET_BASE = "https://testnet.binance.vision/api"
PRODUCTION_BASE = "https://api.binance.com/api"
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
USE_TESTNET = os.environ.get("USE_TESTNET", "true").lower() == "true"
API_KEY = os.environ.get("BINANCE_TESTNET_KEY", "")
API_SECRET = os.environ.get("BINANCE_TESTNET_SECRET", "")
BASE_URL = TESTNET_BASE if USE_TESTNET else PRODUCTION_BASE
TRADE_LOG = []


def _sign(params):
    query = urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + signature


def _request(method, endpoint, params=None, signed=False):
    url = f"{BASE_URL}{endpoint}"
    headers = {"X-MBX-APIKEY": API_KEY}
    if params is None:
        params = {}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        body = _sign(params)
        if method == "GET":
            url += "?" + body
            body = None
        else:
            body = body.encode()
    else:
        if params and method == "GET":
            url += "?" + urlencode(params)
            body = None
        else:
            body = urlencode(params).encode() if params else None
    req = Request(url, data=body if method == "POST" else None, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def get_account():
    return _request("GET", "/v3/account", signed=True)


def get_balance(asset="USDT"):
    account = get_account()
    if "error" in account:
        return {"asset": asset, "free": 0, "locked": 0, "error": account["error"]}
    for b in account.get("balances", []):
        if b["asset"] == asset:
            return {"asset": asset, "free": float(b["free"]), "locked": float(b["locked"])}
    return {"asset": asset, "free": 0, "locked": 0}


def get_price(symbol):
    result = _request("GET", "/v3/ticker/price", {"symbol": symbol})
    if "error" in result:
        return 0
    return float(result.get("price", 0))


def place_order(symbol, side, quantity, order_type="MARKET"):
    ts = datetime.now(timezone.utc).isoformat()
    if DRY_RUN:
        price = get_price(symbol)
        log_entry = {"timestamp": ts, "mode": "DRY_RUN", "symbol": symbol, "side": side, "quantity": quantity, "price": price, "notional": round(price * quantity, 2), "status": "SIMULATED"}
        TRADE_LOG.append(log_entry)
        print(f"[DRY_RUN] {ts} | {side} {quantity} {symbol} @ {price} = ${log_entry['notional']}")
        return log_entry
    params = {"symbol": symbol, "side": side, "type": order_type, "quantity": quantity}
    result = _request("POST", "/v3/order", params, signed=True)
    log_entry = {"timestamp": ts, "mode": "TESTNET" if USE_TESTNET else "LIVE", "symbol": symbol, "side": side, "quantity": quantity, "result": result, "status": result.get("status", "ERROR")}
    TRADE_LOG.append(log_entry)
    return log_entry


def execute_signal(symbol, signal, portfolio_pct=0.05):
    if signal.get("action") not in ("ENTER", "EXIT"):
        return None
    price = get_price(symbol)
    if price == 0:
        return {"error": f"Could not get price for {symbol}"}
    if signal["action"] == "ENTER":
        usdt = get_balance("USDT")
        available = usdt["free"] * portfolio_pct
        raw_qty = available / price
        qty = math.floor(raw_qty * 1000) / 1000
        if qty <= 0:
            return {"error": f"Insufficient balance: ${usdt['free']:.2f} USDT"}
        side = "BUY" if signal.get("side", "LONG") == "LONG" else "SELL"
        return place_order(symbol, side, qty)
    elif signal["action"] == "EXIT":
        base_asset = symbol.replace("USDT", "")
        balance = get_balance(base_asset)
        qty = math.floor(balance["free"] * 1000) / 1000
        if qty <= 0:
            return {"error": f"No {base_asset} to sell"}
        return place_order(symbol, "SELL", qty)


def get_open_orders(symbol=None):
    params = {}
    if symbol:
        params["symbol"] = symbol
    return _request("GET", "/v3/openOrders", params, signed=True)


def get_trade_log():
    return TRADE_LOG


def get_portfolio_summary():
    account = get_account()
    if "error" in account:
        return {"error": account["error"]}
    positions = []
    total_usd = 0
    for b in account.get("balances", []):
        free = float(b["free"])
        locked = float(b["locked"])
        total = free + locked
        if total > 0.001:
            if b["asset"] == "USDT":
                usd_value = total
            else:
                price = get_price(b["asset"] + "USDT")
                usd_value = total * price
            positions.append({"asset": b["asset"], "free": free, "locked": locked, "total": total, "usd_value": round(usd_value, 2)})
            total_usd += usd_value
    return {"positions": sorted(positions, key=lambda x: x["usd_value"], reverse=True), "total_usd": round(total_usd, 2), "mode": "TESTNET" if USE_TESTNET else "LIVE", "dry_run": DRY_RUN, "trades_this_session": len(TRADE_LOG)}


if __name__ == "__main__":
    print(f"Mode: {'DRY_RUN' if DRY_RUN else 'TESTNET' if USE_TESTNET else 'LIVE'}")
    print(f"Base URL: {BASE_URL}")
    if API_KEY:
        print(json.dumps(get_portfolio_summary(), indent=2))
    else:
        print("No API key. Get keys at: https://testnet.binance.vision")
