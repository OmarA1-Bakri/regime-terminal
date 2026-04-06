"""
Trailing Stop Strategy with Ladder Buys
========================================
From: "Claude Just Changed the Stock Market Forever" by Samin Yasar

Strategy:
- Buy a stock, set a trailing stop floor
- As price rises, drag the floor up (it never goes down)
- If price hits the floor, sell everything
- On dips, ladder buy more shares at preset levels
- After selling, look for the next entry

Configuration per position:
- stop_pct: initial stop loss % below entry (e.g., 0.10 = 10%)
- trail_pct: trail % below peak (e.g., 0.05 = 5%)
- trail_activation: % gain before trailing kicks in (e.g., 0.10 = 10%)
- ladder_levels: list of (dip_pct, shares_to_buy)
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import alpaca_client
alpaca_client.API_KEY = os.getenv("ALPACA_API_KEY", "PKWY36S4PNQFCQDTWSFHNTVARA")
alpaca_client.API_SECRET = os.getenv("ALPACA_API_SECRET", "A8uY6N5fahU5k32z26ZLoy9ViwXKNkqBLb29kMLm9ZfC")

STATE_FILE = Path(__file__).parent.parent / "data_cache" / "trailing_stop_state.json"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"positions": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def setup_position(symbol, shares, stop_pct=0.10, trail_pct=0.05,
                   trail_activation=0.10, ladder_levels=None):
    """
    Buy shares and set up trailing stop with ladder buys.

    Args:
        symbol: Stock ticker
        shares: Initial number of shares to buy
        stop_pct: Initial stop loss % (0.10 = sell if drops 10%)
        trail_pct: Trail % below peak once activated (0.05 = 5%)
        trail_activation: % gain before trailing kicks in (0.10 = 10%)
        ladder_levels: List of (dip_pct, extra_shares) for ladder buys
            e.g., [(0.20, 10), (0.30, 20)] = buy 10 more at -20%, 20 more at -30%
    """
    if ladder_levels is None:
        ladder_levels = [(0.15, shares), (0.20, shares * 2), (0.30, shares * 3)]

    # Place market buy
    print(f"Buying {shares} shares of {symbol}...")
    order = alpaca_client.place_order(symbol, shares, "buy", "market", "day")
    print(f"  Order: {order.get('status', 'unknown')} — ID: {order.get('id', '')}")

    time.sleep(2)

    # Get fill price
    pos = alpaca_client.get_position(symbol)
    if pos:
        entry_price = float(pos["avg_entry_price"])
    else:
        snap = alpaca_client.get_snapshot(symbol)
        entry_price = float(snap["latestTrade"]["p"])

    floor_price = entry_price * (1 - stop_pct)

    state = load_state()
    state["positions"][symbol] = {
        "entry_price": entry_price,
        "shares": shares,
        "floor_price": round(floor_price, 2),
        "peak_price": entry_price,
        "stop_pct": stop_pct,
        "trail_pct": trail_pct,
        "trail_activation": trail_activation,
        "trailing_active": False,
        "ladder_levels": ladder_levels,
        "ladder_filled": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_state(state)

    print(f"  Entry: ${entry_price:.2f}")
    print(f"  Floor: ${floor_price:.2f} ({stop_pct*100:.0f}% stop)")
    print(f"  Trail activates at: ${entry_price * (1 + trail_activation):.2f} "
          f"({trail_activation*100:.0f}% gain)")
    print(f"  Ladder levels: {ladder_levels}")
    return state["positions"][symbol]


def check_and_manage():
    """
    Check all trailing stop positions. Called on a schedule (e.g., every 5 min).

    For each position:
    1. Update peak price if new high
    2. Activate trailing stop if gain >= activation threshold
    3. Move floor up if trailing is active
    4. Check ladder buy levels
    5. Sell if price hits floor
    """
    state = load_state()
    if not state["positions"]:
        print("No active trailing stop positions.")
        return []

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"\n[{ts}] Trailing Stop Check")

    actions = []
    positions = alpaca_client.get_positions()
    pos_map = {p["symbol"]: p for p in positions}

    for symbol, cfg in list(state["positions"].items()):
        pos = pos_map.get(symbol)
        if not pos:
            print(f"  {symbol}: No position found (may have been sold)")
            continue

        price = float(pos["current_price"])
        entry = cfg["entry_price"]
        floor = cfg["floor_price"]
        peak = cfg["peak_price"]
        pnl = float(pos["unrealized_pl"])
        pnl_pct = float(pos["unrealized_plpc"]) * 100
        qty = float(pos["qty"])

        # Update peak
        if price > peak:
            cfg["peak_price"] = price
            peak = price

        # Check trailing activation
        gain_pct = (price - entry) / entry
        if not cfg["trailing_active"] and gain_pct >= cfg["trail_activation"]:
            cfg["trailing_active"] = True
            new_floor = price * (1 - cfg["trail_pct"])
            if new_floor > floor:
                cfg["floor_price"] = round(new_floor, 2)
                floor = cfg["floor_price"]
            print(f"  {symbol}: TRAILING ACTIVATED at ${price:.2f} "
                  f"(+{gain_pct*100:.1f}%) — new floor ${floor:.2f}")

        # Move floor up if trailing
        if cfg["trailing_active"]:
            new_floor = peak * (1 - cfg["trail_pct"])
            if new_floor > floor:
                cfg["floor_price"] = round(new_floor, 2)
                floor = cfg["floor_price"]

        # Check floor hit → SELL
        if price <= floor:
            print(f"  {symbol}: FLOOR HIT ${price:.2f} <= ${floor:.2f} — SELLING ALL")
            try:
                alpaca_client.close_position(symbol)
                actions.append({
                    "symbol": symbol, "action": "SOLD", "price": price,
                    "pnl": pnl, "reason": "floor_hit",
                })
                del state["positions"][symbol]
            except Exception as e:
                print(f"    ERROR: {e}")
            continue

        # Check ladder buys
        dip_pct = (entry - price) / entry
        for level_pct, level_shares in cfg["ladder_levels"]:
            level_key = f"{level_pct}"
            if level_key in cfg["ladder_filled"]:
                continue
            if dip_pct >= level_pct:
                print(f"  {symbol}: LADDER BUY at -{level_pct*100:.0f}% — "
                      f"buying {level_shares} more shares")
                try:
                    alpaca_client.buy(symbol, level_shares)
                    cfg["ladder_filled"].append(level_key)
                    cfg["shares"] += level_shares
                    actions.append({
                        "symbol": symbol, "action": "LADDER_BUY",
                        "shares": level_shares, "price": price,
                    })
                except Exception as e:
                    print(f"    ERROR: {e}")

        # Status
        trail_status = "ACTIVE" if cfg["trailing_active"] else "waiting"
        dist_floor = ((price - floor) / price) * 100
        print(f"  {symbol}: ${price:.2f} P&L={pnl_pct:+.1f}% "
              f"Floor=${floor:.2f} ({dist_floor:.1f}% above) "
              f"Peak=${peak:.2f} Trail={trail_status}")

    save_state(state)
    return actions


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", help="Set up trailing stop: SYMBOL:SHARES")
    parser.add_argument("--check", action="store_true", help="Run check cycle")
    parser.add_argument("--loop", type=int, default=0, help="Loop interval in seconds")
    parser.add_argument("--status", action="store_true", help="Show current state")
    args = parser.parse_args()

    if args.setup:
        sym, shares = args.setup.split(":")
        setup_position(sym.upper(), int(shares))
    elif args.check:
        check_and_manage()
    elif args.loop:
        while True:
            check_and_manage()
            time.sleep(args.loop)
    elif args.status:
        state = load_state()
        print(json.dumps(state, indent=2))
    else:
        parser.print_help()
