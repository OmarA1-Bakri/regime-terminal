"""
Position Monitor — watches open positions against stop/target levels.
Run: python -m src.position_monitor
"""
import os, sys, time, json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ALPACA_API_KEY", "PKWY36S4PNQFCQDTWSFHNTVARA")
os.environ.setdefault("ALPACA_API_SECRET", "A8uY6N5fahU5k32z26ZLoy9ViwXKNkqBLb29kMLm9ZfC")

from src import alpaca_client
alpaca_client.API_KEY = os.environ["ALPACA_API_KEY"]
alpaca_client.API_SECRET = os.environ["ALPACA_API_SECRET"]

# Trade plan: symbol -> {stop, target, atr, entry, lowest_seen}
TRADES = {
    "TSLA":  {"stop": 378.56, "target": 289.59, "atr": 14.83, "entry": 348.79, "lowest": 999999},
    "MSTR":  {"stop": 141.40, "target": 92.99,  "atr": 8.07,  "entry": 125.23, "lowest": 999999},
    "COIN":  {"stop": 197.41, "target": 129.27, "atr": 11.36, "entry": 174.66, "lowest": 999999},
}
TRAIL_ATR_MULT = 2.5

def check_positions():
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    positions = alpaca_client.get_positions()
    if not positions:
        print(f"[{ts}] No open positions. All trades closed.")
        return False  # stop loop

    print(f"\n[{ts}] === POSITION CHECK ===")
    total_pnl = 0
    for p in positions:
        sym = p["symbol"]
        price = float(p["current_price"])
        entry = float(p["avg_entry_price"])
        pnl = float(p["unrealized_pl"])
        pnl_pct = float(p["unrealized_plpc"]) * 100
        qty = abs(float(p["qty"]))
        total_pnl += pnl

        trade = TRADES.get(sym)
        if not trade:
            print(f"  {sym}: ${price:.2f} P&L=${pnl:.2f} ({pnl_pct:+.2f}%) [unmanaged]")
            continue

        # Update trailing low
        if price < trade["lowest"]:
            trade["lowest"] = price

        trail_stop = trade["lowest"] + TRAIL_ATR_MULT * trade["atr"]
        effective_stop = min(trade["stop"], trail_stop)

        action = None
        reason = None

        # SHORT: price UP = bad, price DOWN = good
        if price >= effective_stop:
            if price >= trade["stop"]:
                reason = f"HARD STOP (price ${price:.2f} >= stop ${trade['stop']:.2f})"
            else:
                reason = f"TRAIL STOP (price ${price:.2f} >= trail ${trail_stop:.2f}, low was ${trade['lowest']:.2f})"
            action = "close"
        elif price <= trade["target"]:
            reason = f"TARGET HIT (price ${price:.2f} <= target ${trade['target']:.2f})"
            action = "close"

        status = "HOLD"
        if action == "close":
            status = "CLOSING"
            try:
                alpaca_client.close_position(sym)
                status = f"CLOSED — {reason}"
            except Exception as e:
                status = f"CLOSE FAILED: {e}"

        dist_stop = ((effective_stop - price) / price) * 100
        dist_target = ((price - trade["target"]) / price) * 100

        print(f"  {sym}: ${price:.2f} | P&L=${pnl:+.2f} ({pnl_pct:+.2f}%) | "
              f"Stop:{dist_stop:+.1f}% Target:{dist_target:+.1f}% | {status}")

    print(f"  TOTAL P&L: ${total_pnl:+.2f}")
    return True  # keep running

def run_loop(interval=300):
    print(f"Position monitor started (every {interval}s)")
    print(f"Managing: {', '.join(TRADES.keys())}")
    while True:
        try:
            keep_going = check_positions()
            if not keep_going:
                break
        except Exception as e:
            print(f"  ERROR: {e}")
        time.sleep(interval)

if __name__ == "__main__":
    if "--once" in sys.argv:
        check_positions()
    else:
        run_loop(300)
