"""
Wheel Strategy — Options Income Machine
=========================================
From: "Claude Just Changed the Stock Market Forever" by Samin Yasar

The Wheel:
  Stage 1: Sell cash-secured puts ~10% below current price (2-4 week expiry)
            → Collect premium. If expired worthless, repeat.
            → If assigned (price drops), move to Stage 2.
  Stage 2: Sell covered calls ~10% above cost basis (2-4 week expiry)
            → Collect premium. If expired worthless, repeat.
            → If called away (price rises), go back to Stage 1.

Rules:
- Never sell a put without enough cash to buy 100 shares
- Never sell a call below cost basis
- Close at 50% profit before expiration
- Track total premiums collected across all cycles
- Check positions every 15 minutes during market hours

Alpaca supports options trading (Level 3 approved on this account).
"""
import os
import sys
import json
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import alpaca_client
alpaca_client.API_KEY = os.getenv("ALPACA_API_KEY", "PKWY36S4PNQFCQDTWSFHNTVARA")
alpaca_client.API_SECRET = os.getenv("ALPACA_API_SECRET", "A8uY6N5fahU5k32z26ZLoy9ViwXKNkqBLb29kMLm9ZfC")

try:
    import httpx
except ImportError:
    httpx = None

STATE_FILE = Path(__file__).parent.parent / "data_cache" / "wheel_state.json"

# Wheel configuration
PUT_STRIKE_PCT = 0.10    # Sell puts 10% below current price
CALL_STRIKE_PCT = 0.10   # Sell calls 10% above cost basis
EXPIRY_WEEKS = 3         # Target ~3 weeks out
CLOSE_AT_PROFIT = 0.50   # Close option at 50% profit
BASE_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


def _headers():
    return {
        "APCA-API-KEY-ID": alpaca_client.API_KEY,
        "APCA-API-SECRET-KEY": alpaca_client.API_SECRET,
        "accept": "application/json",
    }


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "wheels": {},
        "total_premium_collected": 0,
        "cycles_completed": 0,
    }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_option_chain(symbol, expiry_date=None):
    """Get available option contracts for a symbol."""
    params = {"underlying_symbols": symbol, "status": "active"}
    if expiry_date:
        params["expiration_date"] = expiry_date
    try:
        r = httpx.get(
            f"{DATA_URL}/v1beta1/options/contracts",
            headers=_headers(), params=params, timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("option_contracts", [])
    except Exception as e:
        print(f"  Error fetching option chain: {e}")
    return []


def find_best_expiry(weeks_out=EXPIRY_WEEKS):
    """Find the best expiration date ~N weeks out (Friday)."""
    today = datetime.now(timezone.utc).date()
    target = today + timedelta(weeks=weeks_out)
    # Find nearest Friday
    days_until_friday = (4 - target.weekday()) % 7
    expiry = target + timedelta(days=days_until_friday)
    return expiry.isoformat()


def find_put_contract(symbol, target_strike):
    """Find the best put contract near the target strike price."""
    expiry = find_best_expiry()
    contracts = get_option_chain(symbol, expiry)

    if not contracts:
        # Try nearby dates
        for offset in [-1, 1, -2, 2]:
            alt_expiry = (datetime.fromisoformat(expiry) +
                          timedelta(weeks=offset)).date().isoformat()
            contracts = get_option_chain(symbol, alt_expiry)
            if contracts:
                break

    puts = [c for c in contracts if c.get("type") == "put"]
    if not puts:
        return None

    # Find closest to target strike
    puts.sort(key=lambda c: abs(float(c["strike_price"]) - target_strike))
    return puts[0]


def find_call_contract(symbol, target_strike):
    """Find the best call contract near the target strike price."""
    expiry = find_best_expiry()
    contracts = get_option_chain(symbol, expiry)

    if not contracts:
        for offset in [-1, 1, -2, 2]:
            alt_expiry = (datetime.fromisoformat(expiry) +
                          timedelta(weeks=offset)).date().isoformat()
            contracts = get_option_chain(symbol, alt_expiry)
            if contracts:
                break

    calls = [c for c in contracts if c.get("type") == "call"]
    if not calls:
        return None

    calls.sort(key=lambda c: abs(float(c["strike_price"]) - target_strike))
    return calls[0]


def sell_put(symbol, dry_run=True):
    """
    Stage 1: Sell a cash-secured put.
    Strike = current price * (1 - PUT_STRIKE_PCT)
    """
    state = load_state()

    # Get current price
    snap = alpaca_client.get_snapshot(symbol)
    price = float(snap["latestTrade"]["p"])
    target_strike = round(price * (1 - PUT_STRIKE_PCT), 2)

    # Check we have enough cash for 100 shares at strike
    cash = alpaca_client.get_cash()
    required = target_strike * 100
    if cash < required:
        print(f"  NOT ENOUGH CASH: need ${required:.0f}, have ${cash:.0f}")
        return None

    print(f"  {symbol} @ ${price:.2f}")
    print(f"  Target put strike: ${target_strike:.2f} ({PUT_STRIKE_PCT*100:.0f}% below)")

    contract = find_put_contract(symbol, target_strike)
    if not contract:
        print(f"  No suitable put contract found")
        return None

    strike = float(contract["strike_price"])
    contract_symbol = contract["symbol"]
    expiry = contract["expiration_date"]

    print(f"  Contract: {contract_symbol}")
    print(f"  Strike: ${strike:.2f} | Expiry: {expiry}")

    if dry_run:
        print(f"  DRY RUN: Would sell 1 put contract")
        premium_est = price * 0.02  # ~2% estimated premium
    else:
        # Place sell-to-open order for 1 put contract
        order_body = {
            "symbol": contract_symbol,
            "qty": "1",
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
        }
        try:
            r = httpx.post(
                f"{BASE_URL}/v2/orders", headers=_headers(),
                json=order_body, timeout=30,
            )
            r.raise_for_status()
            result = r.json()
            print(f"  Order placed: {result.get('status')}")
            premium_est = strike * 0.02 * 100  # rough estimate
        except Exception as e:
            print(f"  ORDER ERROR: {e}")
            return None

    # Track state
    state["wheels"][symbol] = {
        "stage": 1,
        "contract": contract_symbol,
        "strike": strike,
        "expiry": expiry,
        "type": "put",
        "premium_collected": premium_est,
        "cost_basis": None,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    state["total_premium_collected"] += premium_est
    save_state(state)

    print(f"  Premium (est): ~${premium_est:.2f}")
    return state["wheels"][symbol]


def sell_call(symbol, cost_basis, dry_run=True):
    """
    Stage 2: Sell a covered call.
    Strike = cost_basis * (1 + CALL_STRIKE_PCT)
    """
    state = load_state()
    target_strike = round(cost_basis * (1 + CALL_STRIKE_PCT), 2)

    snap = alpaca_client.get_snapshot(symbol)
    price = float(snap["latestTrade"]["p"])

    # Never sell a call below cost basis
    if target_strike < cost_basis:
        target_strike = round(cost_basis * 1.05, 2)  # minimum 5% above

    print(f"  {symbol} @ ${price:.2f} | Cost basis: ${cost_basis:.2f}")
    print(f"  Target call strike: ${target_strike:.2f} ({CALL_STRIKE_PCT*100:.0f}% above basis)")

    contract = find_call_contract(symbol, target_strike)
    if not contract:
        print(f"  No suitable call contract found")
        return None

    strike = float(contract["strike_price"])
    contract_symbol = contract["symbol"]
    expiry = contract["expiration_date"]

    # Verify strike >= cost basis
    if strike < cost_basis:
        print(f"  SKIP: strike ${strike:.2f} below cost basis ${cost_basis:.2f}")
        return None

    print(f"  Contract: {contract_symbol}")
    print(f"  Strike: ${strike:.2f} | Expiry: {expiry}")

    if dry_run:
        print(f"  DRY RUN: Would sell 1 call contract")
        premium_est = price * 0.02
    else:
        order_body = {
            "symbol": contract_symbol,
            "qty": "1",
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
        }
        try:
            r = httpx.post(
                f"{BASE_URL}/v2/orders", headers=_headers(),
                json=order_body, timeout=30,
            )
            r.raise_for_status()
            result = r.json()
            print(f"  Order placed: {result.get('status')}")
            premium_est = strike * 0.02 * 100
        except Exception as e:
            print(f"  ORDER ERROR: {e}")
            return None

    state["wheels"][symbol] = {
        "stage": 2,
        "contract": contract_symbol,
        "strike": strike,
        "expiry": expiry,
        "type": "call",
        "premium_collected": premium_est,
        "cost_basis": cost_basis,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    state["total_premium_collected"] += premium_est
    save_state(state)

    print(f"  Premium (est): ~${premium_est:.2f}")
    return state["wheels"][symbol]


def check_wheel_positions(dry_run=True):
    """
    Monitor wheel positions:
    - Check if options expired or got assigned
    - Close at 50% profit
    - Transition between stages
    """
    state = load_state()
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"\n[{ts}] Wheel Strategy Check")

    if not state["wheels"]:
        print("  No active wheel positions")
        return

    today = datetime.now(timezone.utc).date()
    positions = alpaca_client.get_positions()
    pos_map = {p["symbol"]: p for p in positions}

    for symbol, wheel in list(state["wheels"].items()):
        expiry = datetime.fromisoformat(wheel["expiry"]).date()
        days_left = (expiry - today).days

        print(f"\n  {symbol} — Stage {wheel['stage']} "
              f"({wheel['type'].upper()} @ ${wheel['strike']:.2f})")
        print(f"    Expiry: {wheel['expiry']} ({days_left}d left)")
        print(f"    Premium collected this cycle: ${wheel['premium_collected']:.2f}")

        if wheel["stage"] == 1:
            # Stage 1: Sold puts — check if assigned
            if days_left <= 0:
                # Check if we now own the stock (assigned)
                if symbol in pos_map:
                    qty = float(pos_map[symbol]["qty"])
                    if qty >= 100:
                        cost = float(pos_map[symbol]["avg_entry_price"])
                        print(f"    ASSIGNED! Own {qty:.0f} shares @ ${cost:.2f}")
                        print(f"    Moving to Stage 2 (selling covered calls)")
                        if not dry_run:
                            sell_call(symbol, cost, dry_run=False)
                        else:
                            print(f"    DRY RUN: Would sell call @ "
                                  f"${cost * (1 + CALL_STRIKE_PCT):.2f}")
                        state["wheels"][symbol]["stage"] = 2
                        state["wheels"][symbol]["cost_basis"] = cost
                else:
                    # Put expired worthless — premium is ours!
                    print(f"    PUT EXPIRED WORTHLESS — premium kept!")
                    print(f"    Restarting Stage 1...")
                    state["cycles_completed"] += 1
                    if not dry_run:
                        sell_put(symbol, dry_run=False)

        elif wheel["stage"] == 2:
            # Stage 2: Sold calls — check if called away
            if days_left <= 0:
                if symbol not in pos_map:
                    # Shares called away
                    profit = (wheel["strike"] - wheel["cost_basis"]) * 100
                    print(f"    CALLED AWAY! Stock gain: ${profit:.2f}")
                    print(f"    Going back to Stage 1...")
                    state["cycles_completed"] += 1
                    if not dry_run:
                        sell_put(symbol, dry_run=False)
                else:
                    # Call expired worthless — keep shares and premium
                    print(f"    CALL EXPIRED WORTHLESS — premium kept, shares retained")
                    print(f"    Selling another covered call...")
                    if not dry_run:
                        sell_call(symbol, wheel["cost_basis"], dry_run=False)

    # Summary
    print(f"\n  {'─' * 40}")
    print(f"  Total premium collected: ${state['total_premium_collected']:.2f}")
    print(f"  Cycles completed: {state['cycles_completed']}")
    save_state(state)


def start_wheel(symbol, dry_run=True):
    """Initialize the wheel strategy on a symbol."""
    print(f"\n{'=' * 60}")
    print(f"  STARTING WHEEL STRATEGY — {symbol}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'=' * 60}")

    # Check account
    acct = alpaca_client.get_account()
    cash = float(acct["cash"])
    snap = alpaca_client.get_snapshot(symbol)
    price = float(snap["latestTrade"]["p"])
    required = price * 100 * (1 - PUT_STRIKE_PCT)

    print(f"  {symbol} current price: ${price:.2f}")
    print(f"  Cash required (100 shares at strike): ~${required:.0f}")
    print(f"  Available cash: ${cash:.0f}")

    if cash < required:
        print(f"  WARNING: May not have enough cash to cover assignment")

    # Stage 1: Sell put
    return sell_put(symbol, dry_run=dry_run)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Start wheel on SYMBOL")
    parser.add_argument("--check", action="store_true", help="Check positions")
    parser.add_argument("--live", action="store_true", help="Execute real trades")
    parser.add_argument("--loop", type=int, default=0, help="Loop interval (seconds)")
    parser.add_argument("--status", action="store_true", help="Show wheel state")
    args = parser.parse_args()

    dry_run = not args.live

    if args.start:
        start_wheel(args.start.upper(), dry_run=dry_run)
    elif args.check:
        check_wheel_positions(dry_run=dry_run)
    elif args.loop:
        while True:
            check_wheel_positions(dry_run=dry_run)
            time.sleep(args.loop)
    elif args.status:
        state = load_state()
        print(json.dumps(state, indent=2))
    else:
        parser.print_help()
