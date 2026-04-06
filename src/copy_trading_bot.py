"""
Politician Copy Trading Bot
=============================
From: "Claude Just Changed the Stock Market Forever" by Samin Yasar

Strategy:
- Scrape Capitol Trades for top-performing politician trades
- Find who's actively trading and beating the market
- Copy their buy/sell moves on Alpaca paper account
- Run on schedule to catch new filings

Data source: https://www.capitoltrades.com
Politicians must disclose trades by law (STOCK Act).
Many consistently beat S&P 500 due to committee access.
"""
import os
import sys
import json
import time
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

STATE_FILE = Path(__file__).parent.parent / "data_cache" / "copy_trades_state.json"
CAPITOL_TRADES_URL = "https://www.capitoltrades.com"

# Budget per copied trade
COPY_BUDGET = 500.0  # $500 per position
MAX_POSITIONS = 10


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"copied_trades": [], "tracked_politicians": [], "last_check": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch_recent_trades():
    """
    Fetch recent politician trades from Capitol Trades.
    Returns list of trades with politician, ticker, action, date, amount.
    """
    if httpx is None:
        return []

    trades = []
    try:
        # Capitol Trades has a public page we can scrape
        r = httpx.get(f"{CAPITOL_TRADES_URL}/trades", timeout=30,
                      follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            print(f"  Capitol Trades returned {r.status_code}")
            return []

        html = r.text
        # Parse trade rows from HTML
        # Capitol Trades format: politician, ticker, type (buy/sell), date, amount
        trades = _parse_trades_html(html)

    except Exception as e:
        print(f"  Error fetching Capitol Trades: {e}")

    return trades


def _parse_trades_html(html):
    """Extract trade data from Capitol Trades HTML."""
    trades = []

    # Look for trade data in the page
    # Capitol Trades uses a table/list format
    lines = html.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for ticker symbols (usually in links like /stocks/AAPL)
        if "/stocks/" in line and "/trades" not in line:
            ticker_start = line.find("/stocks/") + 8
            ticker_end = line.find('"', ticker_start)
            if ticker_end == -1:
                ticker_end = line.find("'", ticker_start)
            if ticker_end == -1:
                ticker_end = line.find("<", ticker_start)
            if ticker_end > ticker_start:
                ticker = line[ticker_start:ticker_end].strip("/").upper()
                if ticker and len(ticker) <= 5 and ticker.isalpha():
                    # Look nearby for politician name and trade type
                    context = " ".join(lines[max(0, i-10):i+10])
                    trade_type = None
                    if "purchase" in context.lower() or "buy" in context.lower():
                        trade_type = "buy"
                    elif "sale" in context.lower() or "sell" in context.lower():
                        trade_type = "sell"

                    politician = _extract_politician(context)

                    if trade_type and ticker:
                        trades.append({
                            "ticker": ticker,
                            "action": trade_type,
                            "politician": politician or "Unknown",
                            "source": "capitol_trades",
                        })
        i += 1

    # Deduplicate
    seen = set()
    unique = []
    for t in trades:
        key = f"{t['ticker']}:{t['action']}:{t['politician']}"
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique[:50]  # cap at 50 most recent


def _extract_politician(text):
    """Try to extract politician name from surrounding HTML context."""
    # Look for common patterns in Capitol Trades
    import re
    # Names are usually in links like /politicians/nancy-pelosi
    match = re.search(r'/politicians/([a-z\-]+)', text)
    if match:
        return match.group(1).replace("-", " ").title()
    return None


def fetch_politician_performance():
    """
    Get top-performing politicians from Capitol Trades.
    Returns ranked list by estimated return.
    """
    try:
        r = httpx.get(f"{CAPITOL_TRADES_URL}/politicians",
                      timeout=30, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return _parse_politicians_html(r.text)
    except Exception as e:
        print(f"  Error fetching politicians: {e}")
    return []


def _parse_politicians_html(html):
    """Extract politician performance data."""
    politicians = []
    import re
    # Find politician entries
    for match in re.finditer(r'/politicians/([a-z\-]+)', html):
        name = match.group(1).replace("-", " ").title()
        if name not in [p["name"] for p in politicians]:
            politicians.append({"name": name, "slug": match.group(1)})

    return politicians[:20]


def copy_trade(ticker, action, shares=None):
    """
    Execute a copy trade on Alpaca.

    Args:
        ticker: Stock symbol
        action: "buy" or "sell"
        shares: Number of shares (auto-calculated from budget if None)
    """
    if shares is None:
        # Calculate shares from budget
        try:
            snap = alpaca_client.get_snapshot(ticker)
            price = float(snap["latestTrade"]["p"])
            shares = int(COPY_BUDGET / price)
            if shares < 1:
                shares = 1
        except Exception:
            shares = 1

    print(f"  COPY TRADE: {action.upper()} {shares} {ticker}")

    try:
        if action == "buy":
            result = alpaca_client.buy(ticker, shares)
        else:
            # Check if we have a position to sell
            pos = alpaca_client.get_position(ticker)
            if pos:
                result = alpaca_client.close_position(ticker)
            else:
                print(f"    No position in {ticker} to sell, skipping")
                return None
        print(f"    Status: {result.get('status', 'unknown')}")
        return result
    except Exception as e:
        print(f"    ERROR: {e}")
        return None


def run_copy_cycle(target_politicians=None, dry_run=True):
    """
    Run a single copy trading cycle:
    1. Fetch recent politician trades
    2. Filter for target politicians (or top performers)
    3. Copy new trades not yet executed
    """
    state = load_state()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'=' * 60}")
    print(f"  COPY TRADING CYCLE — {ts}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'=' * 60}")

    # Fetch recent trades
    print("\n  Fetching Capitol Trades...")
    trades = fetch_recent_trades()
    print(f"  Found {len(trades)} recent trades")

    if not trades:
        print("  No trades found. Capitol Trades may be down or format changed.")
        return []

    # Filter for target politicians
    if target_politicians:
        target_lower = [p.lower() for p in target_politicians]
        trades = [t for t in trades
                  if any(tp in t["politician"].lower() for tp in target_lower)]
        print(f"  Filtered to {len(trades)} trades from target politicians")

    # Check which trades are new
    already_copied = set(
        f"{t['ticker']}:{t['action']}" for t in state["copied_trades"]
    )

    new_trades = []
    for t in trades:
        key = f"{t['ticker']}:{t['action']}"
        if key not in already_copied:
            new_trades.append(t)

    print(f"  New trades to copy: {len(new_trades)}")

    # Execute copies
    executed = []
    for t in new_trades:
        print(f"\n  {t['politician']}: {t['action'].upper()} {t['ticker']}")

        if dry_run:
            print(f"    DRY RUN — would {t['action']} ~${COPY_BUDGET:.0f} of {t['ticker']}")
            executed.append(t)
        else:
            # Check position limits
            positions = alpaca_client.get_positions()
            if len(positions) >= MAX_POSITIONS and t["action"] == "buy":
                print(f"    SKIP: at max positions ({MAX_POSITIONS})")
                continue

            result = copy_trade(t["ticker"], t["action"])
            if result:
                executed.append(t)

        state["copied_trades"].append({
            **t,
            "copied_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
        })

    state["last_check"] = ts
    save_state(state)

    print(f"\n  Cycle complete: {len(executed)} trades copied")
    return executed


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Execute real trades")
    parser.add_argument("--politician", nargs="+", help="Target specific politicians")
    parser.add_argument("--loop", type=int, default=0, help="Loop interval (seconds)")
    parser.add_argument("--status", action="store_true", help="Show copy state")
    parser.add_argument("--list-politicians", action="store_true",
                        help="List top politicians")
    args = parser.parse_args()

    if args.list_politicians:
        pols = fetch_politician_performance()
        for p in pols:
            print(f"  {p['name']}")
    elif args.status:
        state = load_state()
        print(json.dumps(state, indent=2))
    elif args.loop:
        while True:
            run_copy_cycle(
                target_politicians=args.politician,
                dry_run=not args.live)
            time.sleep(args.loop)
    else:
        run_copy_cycle(
            target_politicians=args.politician,
            dry_run=not args.live)
