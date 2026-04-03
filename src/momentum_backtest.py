"""
Crypto Trend Rider — Daily Donchian Breakout Strategy
======================================================
Target: GBP 1,000 -> GBP 10,000 in < 1 year | Max DD < 20%

Result: GBP 5,715 (+471%) over 2.75 years, Max DD 19.9%
        Best 12M window: GBP 4,658 (+366%) DD 11.9%
        Train: +493% DD 19.9% | Test: -3.8% DD 9.7%

Strategy:
- Daily Donchian channel breakout (20-day) for entries
- Close-only exit evaluation (no intra-day wick stops)
- Triple confirmation: DC breakout + EMA trend + momentum filter
- BTC macro filter: no entries when BTC < 55-day EMA
- 3.5x leverage, 15% position sizing, max 1 position
- Hard stop at -9%, trailing stop at 8% from peak, EMA exit

Key characteristics:
- 33 trades, 48% win rate, Profit Factor 3.7
- Average winner: +147%, Average loser: -27%
- Asymmetric payoff: winners are 5.5x larger than losers
- Catches major crypto trends (FET +567%, SOL +374%, DOGE +293%)
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

INITIAL_CAPITAL = 1000.0
TARGET_CAPITAL = 10000.0
MAX_DD_PCT = 20.0
FEE = 0.001

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "SUIUSDT", "FETUSDT", "NEARUSDT",
    "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "ADAUSDT", "DOTUSDT",
]

SPLIT_MS = 1753833600000  # Aug 1 2025

# Optimised parameters (grid-searched across 4,320 configs)
DC_PERIOD = 20      # Donchian channel lookback
EMA_FAST = 28       # Fast EMA for exit signal
EMA_SLOW = 55       # Slow EMA for trend filter + BTC filter
MOM_PERIOD = 14     # Momentum lookback
MOM_MIN = 0.08      # Minimum 8% momentum for entry
HARD_STOP = 0.09    # 9% hard stop loss
TRAIL_PCT = 0.08    # 8% trailing stop from peak
MAX_POS = 1         # Maximum concurrent positions
POS_PCT = 0.15      # 15% of equity per position
LEVERAGE = 3.5      # Fixed leverage
MIN_HOLD = 5        # Minimum 5-day hold period


def ema_calc(v, p):
    """Exponential Moving Average."""
    e = [0.0]*len(v)
    if len(v) < p: return e
    m = 2.0/(p+1)
    e[p-1] = sum(v[:p])/p
    for i in range(p, len(v)):
        e[i] = (v[i]-e[i-1])*m + e[i-1]
    return e


def dc_high(h, p):
    """Donchian Channel High (highest high of last p bars)."""
    u = [0.0]*len(h)
    for i in range(p, len(h)):
        u[i] = max(h[i-p:i])
    return u


def mom_calc(c, p):
    """Rate of change momentum."""
    m = [0.0]*len(c)
    for i in range(p, len(c)):
        if c[i-p] > 0: m[i] = (c[i]-c[i-p])/c[i-p]
    return m


class Position:
    """Tracks an open leveraged long position."""
    def __init__(self, sym, entry, alloc, bar, lev):
        self.sym = sym
        self.entry = entry
        self.alloc = alloc
        self.bar = bar
        self.lev = lev
        self.peak = entry
        self.hard_stop_price = entry * (1 - HARD_STOP)

    def check_exit(self, close, ema_fast_val):
        """Evaluate exit conditions at daily close."""
        if close > self.peak:
            self.peak = close
        if close < self.hard_stop_price:
            return "hard_stop"
        if self.peak > self.entry * 1.02 and close < self.peak * (1 - TRAIL_PCT):
            return "trail_stop"
        if ema_fast_val > 0 and close < ema_fast_val:
            return "ema_exit"
        return None

    def pnl(self, exit_price):
        """Calculate leveraged P&L as a fraction of allocation."""
        raw = (exit_price - self.entry) / self.entry
        return raw * self.lev - FEE * self.lev


def backtest(data, start_ms=None, end_ms=None):
    """Run the strategy backtest on daily candle data."""
    init = INITIAL_CAPITAL
    eq = init
    peak_eq = init
    max_dd = 0
    positions = {}
    trades = []
    cooldowns = {}
    equity_curve = []

    # Pre-compute indicators for each symbol
    indicators = {}
    for sym, candles in data.items():
        c = [x[4] for x in candles]
        h = [x[2] for x in candles]
        t = [x[0] for x in candles]
        indicators[sym] = {
            "c": c, "h": h, "t": t,
            "dc": dc_high(h, DC_PERIOD),
            "ef": ema_calc(c, EMA_FAST),
            "es": ema_calc(c, EMA_SLOW),
            "mom": mom_calc(c, MOM_PERIOD),
            "ti": {tt: i for i, tt in enumerate(t)},
        }

    # Collect all timestamps in range
    times = set()
    for v in indicators.values():
        for tt in v["t"]:
            if start_ms and tt < start_ms: continue
            if end_ms and tt >= end_ms: continue
            times.add(tt)
    timeline = sorted(times)

    for bar, t in enumerate(timeline):
        # --- EXITS ---
        closed = []
        for sym, pos in list(positions.items()):
            d = indicators.get(sym)
            if not d or t not in d["ti"]: continue
            i = d["ti"][t]
            if bar - pos.bar < MIN_HOLD:
                if d["c"][i] > pos.peak:
                    pos.peak = d["c"][i]
                continue
            reason = pos.check_exit(d["c"][i], d["ef"][i])
            if reason:
                pnl_val = pos.pnl(d["c"][i])
                gbp = pos.alloc * pnl_val
                eq += gbp
                trades.append({
                    "sym": sym, "pnl%": pnl_val * 100, "gbp": gbp,
                    "raw%": (d["c"][i] - pos.entry) / pos.entry * 100,
                    "bars": bar - pos.bar, "reason": reason, "lev": pos.lev,
                })
                closed.append(sym)
                cooldowns[sym] = 3  # 3-day cooldown after exit

        for sym in closed:
            del positions[sym]
        for sym in list(cooldowns):
            cooldowns[sym] -= 1
            if cooldowns[sym] <= 0: del cooldowns[sym]

        # --- MARK-TO-MARKET ---
        mtm = eq
        for sym, pos in positions.items():
            d = indicators.get(sym)
            if d and t in d["ti"]:
                i = d["ti"][t]
                mtm += pos.alloc * (d["c"][i] - pos.entry) / pos.entry * pos.lev
        peak_eq = max(peak_eq, mtm)
        dd = (peak_eq - mtm) / peak_eq * 100 if peak_eq > 0 else 0
        max_dd = max(max_dd, dd)
        equity_curve.append((t, mtm, dd))

        # --- BTC MACRO FILTER ---
        btc = indicators.get("BTCUSDT")
        btc_bullish = True
        if btc and t in btc["ti"]:
            bi = btc["ti"][t]
            if btc["es"][bi] > 0 and btc["c"][bi] < btc["es"][bi]:
                btc_bullish = False

        # --- ENTRIES ---
        if btc_bullish and len(positions) < MAX_POS:
            dd_scale = max(0.3, 1.0 - dd / (MAX_DD_PCT * 1.3))
            candidates = []
            for sym in SYMBOLS:
                if sym in positions or sym in cooldowns: continue
                d = indicators.get(sym)
                if not d or t not in d["ti"]: continue
                i = d["ti"][t]
                if i < EMA_SLOW + 5: continue
                cl, hi = d["c"][i], d["h"][i]
                dc, es, ef, mo = d["dc"][i], d["es"][i], d["ef"][i], d["mom"][i]
                if es <= 0 or dc <= 0: continue
                # Entry: breakout + trend + momentum
                if hi > dc and cl > es and ef > es and mo > MOM_MIN:
                    candidates.append({"sym": sym, "price": cl, "mom": mo})

            candidates.sort(key=lambda x: x["mom"], reverse=True)
            for c in candidates[:MAX_POS - len(positions)]:
                alloc = eq * POS_PCT * dd_scale
                if alloc < 10: continue
                positions[c["sym"]] = Position(
                    c["sym"], c["price"], alloc, bar, LEVERAGE
                )

    # Close remaining positions at end
    if timeline:
        t = timeline[-1]
        for sym, pos in list(positions.items()):
            d = indicators.get(sym)
            if d and t in d["ti"]:
                i = d["ti"][t]
                pnl_val = pos.pnl(d["c"][i])
                gbp = pos.alloc * pnl_val
                eq += gbp
                trades.append({
                    "sym": sym, "pnl%": pnl_val * 100, "gbp": gbp,
                    "raw%": (d["c"][i] - pos.entry) / pos.entry * 100,
                    "bars": len(timeline) - pos.bar, "reason": "end", "lev": pos.lev,
                })

    # Compute statistics
    ret = (eq - init) / init * 100
    wins = [t for t in trades if t["pnl%"] > 0]
    losses = [t for t in trades if t["pnl%"] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t["pnl%"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl%"] for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t["gbp"] for t in wins)
    gross_loss = abs(sum(t["gbp"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    return {
        "final": round(eq, 2), "ret%": round(ret, 2), "dd": round(max_dd, 2),
        "trades": len(trades), "wr": round(wr, 1),
        "aw": round(avg_win, 2), "al": round(avg_loss, 2),
        "pf": round(profit_factor, 2),
        "target": eq >= TARGET_CAPITAL, "dd_ok": max_dd <= MAX_DD_PCT,
    }, trades, equity_curve


def print_results(label, r, trades=None, show_trades=True):
    dd_ok = "OK" if r["dd_ok"] else "DD!"
    target = "10x!" if r["target"] else ""
    print(f"\n--- {label} ---")
    print(f"  GBP {r['final']:>10,.2f} ({r['ret%']:>+.1f}%) DD:{r['dd']:.1f}%[{dd_ok}] {target}")
    print(f"  {r['trades']}t WR:{r['wr']:.0f}% AvgW:{r['aw']:+.1f}% AvgL:{r['al']:+.1f}% PF:{r['pf']:.2f}")
    if show_trades and trades:
        tr_sorted = sorted(trades, key=lambda x: abs(x["gbp"]), reverse=True)
        print(f"  Trades (by |GBP|):")
        for t in tr_sorted[:12]:
            print(f"    {t['sym']:12s} {t['reason']:10s} Raw:{t['raw%']:>+6.1f}% "
                  f"Lev:{t['pnl%']:>+7.1f}% GBP{t['gbp']:>+9.2f} {t['bars']}d {t['lev']:.1f}x")


def run():
    from src.data_fetcher import fetch_all_symbols
    print("Fetching daily data...")
    data = fetch_all_symbols(SYMBOLS, interval="1d", start_date="2023-06-01", end_date="2026-03-31")

    print(f"\n{'='*65}")
    print(f"CRYPTO TREND RIDER — Daily Donchian Breakout")
    print(f"Config: DC:{DC_PERIOD} EF:{EMA_FAST} ES:{EMA_SLOW} Lev:{LEVERAGE}x")
    print(f"        Pos:{POS_PCT*100:.0f}% Max:{MAX_POS} Trail:{TRAIL_PCT*100:.0f}% HS:{HARD_STOP*100:.0f}%")
    print(f"{'='*65}")

    # Train / Test / Full
    for label, kw in [("TRAIN (Jun23-Aug25)", {"end_ms": SPLIT_MS}),
                       ("TEST (Aug25-Mar26)", {"start_ms": SPLIT_MS}),
                       ("FULL (Jun23-Mar26)", {})]:
        r, tr, _ = backtest(data, **kw)
        print_results(label, r, tr)

    # Rolling 12-month windows
    all_times = sorted(set(c[0] for candles in data.values() for c in candles))
    print(f"\n{'='*65}")
    print(f"ROLLING 12-MONTH WINDOWS")
    print(f"{'='*65}")

    best_12m = None
    windows_valid = 0
    windows_total = 0
    for start_t in all_times[::7]:
        end_t = start_t + 365 * 24 * 3600 * 1000
        if end_t > max(all_times): break
        windows_total += 1
        r, _, _ = backtest(data, start_ms=start_t, end_ms=end_t)
        if r["dd_ok"]:
            windows_valid += 1
            if best_12m is None or r["final"] > best_12m[0]["final"]:
                best_12m = (r, start_t, end_t)

    print(f"  {windows_valid}/{windows_total} windows with DD < 20%")

    if best_12m:
        r, s, e = best_12m
        sd = datetime.fromtimestamp(s/1000, tz=timezone.utc).strftime('%Y-%m-%d')
        ed = datetime.fromtimestamp(e/1000, tz=timezone.utc).strftime('%Y-%m-%d')
        m = "10x!" if r["target"] else ""
        print(f"  Best: {sd} -> {ed}")
        r, tr, _ = backtest(data, start_ms=s, end_ms=e)
        print_results(f"BEST 12M ({sd} to {ed})", r, tr)

    # Last 12 months
    latest = max(c[0] for v in data.values() for c in v)
    r, tr, _ = backtest(data, start_ms=latest - 365*24*3600*1000)
    print_results("LAST 12 MONTHS", r, tr)

    return data


if __name__ == "__main__":
    run()
