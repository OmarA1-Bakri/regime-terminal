"""
Unified Exchange Router
========================
Routes orders to Alpaca (stocks) or Binance (crypto) based on symbol type.
Alpaca: stocks/ETFs — 0% commission, paper trading
Binance: crypto — 0.1% taker fee, testnet

Fee comparison:
    Alpaca Stocks:  $0 commission
    Alpaca Crypto:  0.15% spread + 0.15% fee = ~0.30%
    Binance Crypto: 0.10% taker fee
    → Stocks on Alpaca, Crypto on Binance
"""
import os

# Known crypto symbols (Binance format: BTCUSDT)
CRYPTO_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "RENDERUSDT",
    "FETUSDT", "NEARUSDT", "ARUSDT", "INJUSDT", "SUIUSDT", "PENDLEUSDT",
}

# Alpaca crypto symbols use "/" format
ALPACA_CRYPTO_MAP = {
    "BTCUSDT": "BTC/USD", "ETHUSDT": "ETH/USD", "SOLUSDT": "SOL/USD",
    "BNBUSDT": "BNB/USD", "XRPUSDT": "XRP/USD", "DOGEUSDT": "DOGE/USD",
    "ADAUSDT": "ADA/USD", "AVAXUSDT": "AVAX/USD", "DOTUSDT": "DOT/USD",
    "LINKUSDT": "LINK/USD",
}

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"


def is_crypto(symbol):
    """Check if a symbol is crypto."""
    return symbol.upper() in CRYPTO_SYMBOLS or symbol.endswith("USDT")


def route_exchange(symbol):
    """Determine which exchange to use."""
    if is_crypto(symbol):
        return "binance"
    return "alpaca"


def execute_order(symbol, side, qty, order_type="market", dry_run=None):
    """
    Route and execute an order on the appropriate exchange.

    Returns:
        {
            "exchange": "alpaca" | "binance",
            "symbol": str,
            "side": str,
            "qty": float,
            "status": "filled" | "dry_run" | "error",
            "details": dict,
        }
    """
    if dry_run is None:
        dry_run = DRY_RUN

    exchange = route_exchange(symbol)
    result = {
        "exchange": exchange,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "status": "dry_run" if dry_run else "pending",
        "details": {},
    }

    if dry_run:
        result["status"] = "dry_run"
        result["details"] = {"message": f"DRY RUN: {side} {qty} {symbol} on {exchange}"}
        return result

    try:
        if exchange == "alpaca":
            from src import alpaca_client
            order = alpaca_client.place_order(
                symbol=symbol, qty=qty, side=side, order_type=order_type)
            result["status"] = order.get("status", "submitted")
            result["details"] = order

        elif exchange == "binance":
            from src import paper_trade
            binance_side = "BUY" if side == "buy" else "SELL"
            order = paper_trade.place_order(
                symbol=symbol, side=binance_side, quantity=qty)
            result["status"] = "filled" if order else "error"
            result["details"] = order or {}

    except Exception as e:
        result["status"] = "error"
        result["details"] = {"error": str(e)}

    return result


def execute_bracket(symbol, side, qty, take_profit, stop_loss, dry_run=None):
    """Execute a bracket order (entry + TP + SL)."""
    if dry_run is None:
        dry_run = DRY_RUN

    exchange = route_exchange(symbol)

    if dry_run:
        return {
            "exchange": exchange, "symbol": symbol, "side": side,
            "qty": qty, "status": "dry_run",
            "details": {
                "message": f"DRY RUN bracket: {side} {qty} {symbol}",
                "take_profit": take_profit, "stop_loss": stop_loss,
            },
        }

    if exchange == "alpaca":
        from src import alpaca_client
        order = alpaca_client.place_bracket_order(
            symbol=symbol, qty=qty, side=side,
            take_profit_price=take_profit, stop_loss_price=stop_loss)
        return {
            "exchange": exchange, "symbol": symbol, "side": side,
            "qty": qty, "status": order.get("status", "submitted"),
            "details": order,
        }

    # Binance doesn't natively support bracket orders — use separate orders
    entry_result = execute_order(symbol, side, qty, dry_run=False)
    return entry_result


def get_portfolio(exchange=None):
    """Get combined portfolio from all exchanges."""
    portfolio = {"alpaca": {}, "binance": {}}

    if exchange is None or exchange == "alpaca":
        try:
            from src import alpaca_client
            positions = alpaca_client.get_positions()
            for p in positions:
                portfolio["alpaca"][p["symbol"]] = {
                    "qty": float(p["qty"]),
                    "entry": float(p["avg_entry_price"]),
                    "current": float(p["current_price"]),
                    "pnl": float(p["unrealized_pl"]),
                    "pnl_pct": float(p["unrealized_plpc"]) * 100,
                    "market_value": float(p["market_value"]),
                }
        except Exception:
            pass

    if exchange is None or exchange == "binance":
        try:
            from src import paper_trade
            summary = paper_trade.get_portfolio_summary()
            for pos in summary.get("positions", []):
                portfolio["binance"][pos["symbol"]] = pos
        except Exception:
            pass

    return portfolio


def get_total_equity():
    """Get combined equity across all exchanges."""
    total = 0
    try:
        from src import alpaca_client
        total += alpaca_client.get_equity()
    except Exception:
        pass
    # Binance equity would come from paper_trade module
    return total
