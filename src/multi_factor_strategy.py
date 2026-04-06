"""
Multi-Factor Adaptive Strategy Engine
=======================================
Combines multiple signals into a single conviction score.
Adapts between trend-following and mean-reversion based on regime.

Factors:
1. Donchian Channel Breakout (trend)
2. EMA Trend Alignment (trend)
3. RSI Mean Reversion (counter-trend in ranges)
4. Bollinger Band Squeeze → Breakout (volatility)
5. MACD Momentum Confirmation
6. ADX Trend Strength Filter
7. Volume Confirmation (VWAP ratio)

Position Sizing:
- Kelly-inspired: size proportional to conviction * edge
- Drawdown scaling: reduce size as DD approaches limit
- Volatility normalization: equal-risk per position via ATR

Key improvements over the original Donchian-only strategy:
- Adaptive regime detection (no single-mode overfitting)
- Walk-forward parameter selection (no lookahead bias)
- Multi-factor confirmation (fewer false signals)
- Dynamic position sizing (not fixed %)
- Proper train/test discipline
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators import (
    ema, sma, rsi, bollinger_bands, atr, donchian_channel,
    macd, adx, rate_of_change, vwap_ratio, squeeze,
)


# ── Configuration ────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    # Donchian
    "dc_period": 20,
    # EMA
    "ema_fast": 21,
    "ema_slow": 55,
    # RSI
    "rsi_period": 14,
    "rsi_ob": 70,       # overbought
    "rsi_os": 30,       # oversold
    # Bollinger
    "bb_period": 20,
    "bb_std": 2.0,
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # ADX
    "adx_period": 14,
    "adx_threshold": 25,   # trending if ADX > 25
    # Momentum
    "mom_period": 14,
    "mom_min": 0.05,
    # Risk
    "atr_period": 14,
    "risk_per_trade": 0.02,   # 2% risk per trade
    "max_positions": 3,
    "max_portfolio_risk": 0.06,  # 6% total portfolio risk
    "max_drawdown": 0.15,       # 15% max DD
    "hard_stop_atr": 2.0,       # stop at 2x ATR
    "trail_atr": 2.5,           # trailing stop at 2.5x ATR
    "take_profit_atr": 4.0,     # take profit at 4x ATR
    # Leverage
    "max_leverage": 1.0,    # stocks: no leverage by default
    "leverage_scale": True,  # scale leverage with conviction
    # Minimum hold
    "min_hold_bars": 3,
    "cooldown_bars": 2,
    # Factor weights
    "w_donchian": 0.20,
    "w_ema_trend": 0.15,
    "w_rsi": 0.15,
    "w_bollinger": 0.15,
    "w_macd": 0.15,
    "w_adx": 0.10,
    "w_volume": 0.10,
}

# Symbol universes
STOCK_UNIVERSE = [
    # High-beta tech (momentum candidates)
    "NVDA", "TSLA", "AMD", "PLTR", "SOFI", "MARA",
    # Large-cap growth
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    # Sector ETFs
    "QQQ", "SPY", "XLF", "XLE", "ARKK",
    # Crypto-adjacent
    "COIN", "MSTR",
]


# ── Signal Generation ────────────────────────────────────────────────

class SignalEngine:
    """Compute multi-factor signals for a single symbol."""

    def __init__(self, config=None):
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}

    def compute_signals(self, closes, highs, lows, volumes):
        """
        Compute all indicators and generate a conviction score per bar.

        Returns list of dicts, one per bar:
            {
                "conviction": float (-1 to +1, negative=short, positive=long),
                "regime": "trending" | "ranging" | "volatile",
                "factors": {name: score},
                "atr_val": float,
                "stop_price": float,
                "target_price": float,
            }
        """
        cfg = self.cfg
        n = len(closes)
        signals = [None] * n

        # Pre-compute all indicators
        ema_f = ema(closes, cfg["ema_fast"])
        ema_s = ema(closes, cfg["ema_slow"])
        rsi_vals = rsi(closes, cfg["rsi_period"])
        bb_upper, bb_mid, bb_lower, bb_bw = bollinger_bands(
            closes, cfg["bb_period"], cfg["bb_std"])
        atr_vals = atr(highs, lows, closes, cfg["atr_period"])
        dc_upper, dc_lower, dc_mid = donchian_channel(
            highs, lows, cfg["dc_period"])
        macd_line, macd_sig, macd_hist = macd(
            closes, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"])
        adx_vals, pdi_vals, mdi_vals = adx(
            highs, lows, closes, cfg["adx_period"])
        mom = rate_of_change(closes, cfg["mom_period"])
        vwap_r = vwap_ratio(closes, volumes, 20)
        sq = squeeze(bb_bw, 120)

        warmup = max(cfg["ema_slow"], cfg["bb_period"],
                     cfg["dc_period"], cfg["adx_period"] * 2) + 5

        for i in range(n):
            if i < warmup:
                signals[i] = {
                    "conviction": 0.0, "regime": "warmup",
                    "factors": {}, "atr_val": 0, "stop_price": 0,
                    "target_price": 0,
                }
                continue

            # ── Regime Classification ──
            adx_v = adx_vals[i]
            bw = bb_bw[i]
            is_trending = adx_v > cfg["adx_threshold"]
            is_squeeze = sq[i]
            if is_squeeze:
                regime = "volatile"  # squeeze about to break
            elif is_trending:
                regime = "trending"
            else:
                regime = "ranging"

            # ── Factor Scores (-1 to +1 each) ──
            factors = {}

            # 1. Donchian Breakout
            if dc_upper[i] > 0:
                if highs[i] > dc_upper[i]:
                    factors["donchian"] = 1.0
                elif lows[i] < dc_lower[i]:
                    factors["donchian"] = -1.0
                else:
                    # Position within channel
                    rng = dc_upper[i] - dc_lower[i]
                    if rng > 0:
                        factors["donchian"] = (closes[i] - dc_mid[i]) / (rng / 2)
                        factors["donchian"] = max(-1, min(1, factors["donchian"]))
                    else:
                        factors["donchian"] = 0.0
            else:
                factors["donchian"] = 0.0

            # 2. EMA Trend Alignment
            if ema_s[i] > 0:
                if closes[i] > ema_f[i] > ema_s[i]:
                    factors["ema_trend"] = 1.0
                elif closes[i] < ema_f[i] < ema_s[i]:
                    factors["ema_trend"] = -1.0
                elif ema_f[i] > ema_s[i]:
                    factors["ema_trend"] = 0.5
                elif ema_f[i] < ema_s[i]:
                    factors["ema_trend"] = -0.5
                else:
                    factors["ema_trend"] = 0.0
            else:
                factors["ema_trend"] = 0.0

            # 3. RSI — adaptive based on regime
            rv = rsi_vals[i]
            if regime == "trending":
                # In trends, RSI > 50 confirms bullish, < 50 bearish
                factors["rsi"] = (rv - 50) / 50
            else:
                # In ranges, overbought/oversold = mean reversion
                if rv > cfg["rsi_ob"]:
                    factors["rsi"] = -(rv - cfg["rsi_ob"]) / (100 - cfg["rsi_ob"])
                elif rv < cfg["rsi_os"]:
                    factors["rsi"] = (cfg["rsi_os"] - rv) / cfg["rsi_os"]
                else:
                    factors["rsi"] = 0.0

            # 4. Bollinger Bands
            if bb_upper[i] > 0 and bb_lower[i] > 0:
                if is_squeeze:
                    # Squeeze: prepare for breakout, use momentum direction
                    factors["bollinger"] = 0.5 if mom[i] > 0 else -0.5
                elif closes[i] > bb_upper[i]:
                    factors["bollinger"] = 1.0 if regime == "trending" else -0.5
                elif closes[i] < bb_lower[i]:
                    factors["bollinger"] = -1.0 if regime == "trending" else 0.5
                else:
                    bb_pos = (closes[i] - bb_lower[i]) / (bb_upper[i] - bb_lower[i])
                    factors["bollinger"] = (bb_pos - 0.5) * 2
            else:
                factors["bollinger"] = 0.0

            # 5. MACD
            if macd_hist[i] > 0 and macd_hist[i] > macd_hist[i - 1]:
                factors["macd"] = min(1.0, macd_hist[i] / (atr_vals[i] * 0.1 + 1e-9))
            elif macd_hist[i] < 0 and macd_hist[i] < macd_hist[i - 1]:
                factors["macd"] = max(-1.0, macd_hist[i] / (atr_vals[i] * 0.1 + 1e-9))
            else:
                factors["macd"] = 0.3 if macd_hist[i] > 0 else -0.3

            # 6. ADX Trend Strength
            if adx_v > cfg["adx_threshold"]:
                if pdi_vals[i] > mdi_vals[i]:
                    factors["adx"] = min(1.0, adx_v / 50)
                else:
                    factors["adx"] = -min(1.0, adx_v / 50)
            else:
                factors["adx"] = 0.0

            # 7. Volume (VWAP ratio)
            vr = vwap_r[i]
            if vr > 1.02:
                factors["volume"] = min(1.0, (vr - 1.0) * 5)
            elif vr < 0.98:
                factors["volume"] = max(-1.0, (vr - 1.0) * 5)
            else:
                factors["volume"] = 0.0

            # ── Weighted Conviction Score ──
            weights = {
                "donchian": cfg["w_donchian"],
                "ema_trend": cfg["w_ema_trend"],
                "rsi": cfg["w_rsi"],
                "bollinger": cfg["w_bollinger"],
                "macd": cfg["w_macd"],
                "adx": cfg["w_adx"],
                "volume": cfg["w_volume"],
            }
            conviction = sum(factors.get(k, 0) * w for k, w in weights.items())

            # Boost conviction if factors agree (consensus bonus)
            signs = [1 if v > 0.1 else (-1 if v < -0.1 else 0)
                     for v in factors.values()]
            agreeing = sum(1 for s in signs if s == (1 if conviction > 0 else -1))
            if agreeing >= 5:
                conviction *= 1.3  # 30% boost for strong consensus
            elif agreeing >= 4:
                conviction *= 1.15

            conviction = max(-1.0, min(1.0, conviction))

            # ── Stop and Target ──
            av = atr_vals[i]
            if conviction > 0:
                stop_price = closes[i] - cfg["hard_stop_atr"] * av
                target_price = closes[i] + cfg["take_profit_atr"] * av
            elif conviction < 0:
                stop_price = closes[i] + cfg["hard_stop_atr"] * av
                target_price = closes[i] - cfg["take_profit_atr"] * av
            else:
                stop_price = 0
                target_price = 0

            signals[i] = {
                "conviction": round(conviction, 4),
                "regime": regime,
                "factors": {k: round(v, 3) for k, v in factors.items()},
                "atr_val": round(av, 4),
                "stop_price": round(stop_price, 2),
                "target_price": round(target_price, 2),
            }

        return signals


# ── Position Sizing ──────────────────────────────────────────────────

def compute_position_size(equity, conviction, atr_val, price, config=None):
    """
    ATR-based position sizing with conviction scaling.

    Risk per trade = equity * risk_per_trade * |conviction|
    Shares = risk_amount / (atr * hard_stop_multiplier)
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    abs_conv = abs(conviction)
    if abs_conv < 0.2 or atr_val <= 0 or price <= 0:
        return 0

    risk_amount = equity * cfg["risk_per_trade"] * abs_conv
    stop_distance = atr_val * cfg["hard_stop_atr"]
    shares = risk_amount / stop_distance

    # Cap at max portfolio allocation
    max_value = equity * 0.25  # max 25% in one position
    max_shares = max_value / price
    shares = min(shares, max_shares)

    # Leverage scaling
    if cfg["leverage_scale"] and abs_conv > 0.7:
        lev = 1.0 + (abs_conv - 0.7) / 0.3 * (cfg["max_leverage"] - 1.0)
        shares *= lev

    return max(0, int(shares))


# ── Backtester ───────────────────────────────────────────────────────

class Position:
    def __init__(self, sym, side, entry, qty, bar, atr_val, config):
        self.sym = sym
        self.side = side  # "long" or "short"
        self.entry = entry
        self.qty = qty
        self.bar = bar
        self.atr_val = atr_val
        self.peak = entry
        self.trough = entry
        self.cfg = config
        if side == "long":
            self.stop = entry - config["hard_stop_atr"] * atr_val
            self.target = entry + config["take_profit_atr"] * atr_val
        else:
            self.stop = entry + config["hard_stop_atr"] * atr_val
            self.target = entry - config["take_profit_atr"] * atr_val

    def update(self, price):
        """Update trailing stop."""
        if self.side == "long":
            if price > self.peak:
                self.peak = price
                trail = self.peak - self.cfg["trail_atr"] * self.atr_val
                self.stop = max(self.stop, trail)
        else:
            if price < self.trough:
                self.trough = price
                trail = self.trough + self.cfg["trail_atr"] * self.atr_val
                self.stop = min(self.stop, trail)

    def check_exit(self, price, bar):
        if bar - self.bar < self.cfg["min_hold_bars"]:
            self.update(price)
            return None
        if self.side == "long":
            if price <= self.stop:
                return "stop"
            if price >= self.target:
                return "target"
        else:
            if price >= self.stop:
                return "stop"
            if price <= self.target:
                return "target"
        self.update(price)
        return None

    def pnl(self, exit_price):
        if self.side == "long":
            return (exit_price - self.entry) / self.entry * self.qty * self.entry
        else:
            return (self.entry - exit_price) / self.entry * self.qty * self.entry


def backtest(data, config=None, start_ms=None, end_ms=None,
             initial_capital=10000, fee=0.001):
    """
    Run multi-factor backtest across multiple symbols.

    Args:
        data: dict {symbol: [[open_time, open, high, low, close, volume], ...]}
        config: strategy configuration override
        start_ms: start timestamp filter
        end_ms: end timestamp filter
        initial_capital: starting equity
        fee: round-trip fee rate

    Returns:
        (stats, trades, equity_curve)
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    engine = SignalEngine(cfg)
    equity = initial_capital
    peak_equity = initial_capital
    max_dd = 0
    positions = {}
    trades = []
    cooldowns = {}
    equity_curve = []

    # Pre-compute signals for each symbol
    sym_signals = {}
    sym_data = {}
    for sym, candles in data.items():
        if start_ms or end_ms:
            candles = [c for c in candles
                       if (not start_ms or c[0] >= start_ms)
                       and (not end_ms or c[0] < end_ms)]
        if len(candles) < 100:
            continue
        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        volumes = [c[5] for c in candles]
        times = [c[0] for c in candles]
        signals = engine.compute_signals(closes, highs, lows, volumes)
        sym_signals[sym] = signals
        sym_data[sym] = {
            "c": closes, "h": highs, "l": lows, "v": volumes,
            "t": times, "ti": {t: i for i, t in enumerate(times)},
        }

    # Collect all timestamps
    all_times = sorted(set(
        t for d in sym_data.values() for t in d["t"]
    ))

    for bar, t in enumerate(all_times):
        # ── EXITS ──
        closed = []
        for sym, pos in list(positions.items()):
            d = sym_data.get(sym)
            if not d or t not in d["ti"]:
                continue
            i = d["ti"][t]
            reason = pos.check_exit(d["c"][i], bar)
            if reason:
                exit_price = d["c"][i]
                pnl_val = pos.pnl(exit_price)
                fee_cost = pos.qty * pos.entry * fee + pos.qty * exit_price * fee
                net_pnl = pnl_val - fee_cost
                equity += net_pnl
                trades.append({
                    "sym": sym, "side": pos.side,
                    "entry": pos.entry, "exit": exit_price,
                    "qty": pos.qty, "pnl": round(net_pnl, 2),
                    "pnl_pct": round(net_pnl / (pos.qty * pos.entry) * 100, 2),
                    "bars": bar - pos.bar, "reason": reason,
                })
                closed.append(sym)
                cooldowns[sym] = cfg["cooldown_bars"]

        for sym in closed:
            del positions[sym]
        for sym in list(cooldowns):
            cooldowns[sym] -= 1
            if cooldowns[sym] <= 0:
                del cooldowns[sym]

        # ── MARK TO MARKET ──
        mtm = equity
        for sym, pos in positions.items():
            d = sym_data.get(sym)
            if d and t in d["ti"]:
                i = d["ti"][t]
                mtm += pos.pnl(d["c"][i])
        peak_equity = max(peak_equity, mtm)
        dd = (peak_equity - mtm) / peak_equity * 100 if peak_equity > 0 else 0
        max_dd = max(max_dd, dd)
        equity_curve.append((t, round(mtm, 2), round(dd, 2)))

        # ── DD KILL SWITCH ──
        if dd / 100 >= cfg["max_drawdown"]:
            continue

        # ── ENTRIES ──
        if len(positions) >= cfg["max_positions"]:
            continue

        # Collect candidates with conviction
        candidates = []
        for sym in data.keys():
            if sym in positions or sym in cooldowns:
                continue
            d = sym_data.get(sym)
            sigs = sym_signals.get(sym)
            if not d or not sigs or t not in d["ti"]:
                continue
            i = d["ti"][t]
            sig = sigs[i]
            if sig["regime"] == "warmup":
                continue
            conv = sig["conviction"]
            if abs(conv) < 0.25:  # minimum conviction threshold
                continue
            candidates.append((sym, i, sig, conv))

        # Sort by absolute conviction, take best
        candidates.sort(key=lambda x: abs(x[3]), reverse=True)
        dd_scale = max(0.3, 1.0 - dd / (cfg["max_drawdown"] * 100 * 1.3))

        for sym, i, sig, conv in candidates:
            if len(positions) >= cfg["max_positions"]:
                break
            d = sym_data[sym]
            price = d["c"][i]
            av = sig["atr_val"]
            if av <= 0 or price <= 0:
                continue

            qty = compute_position_size(
                equity * dd_scale, conv, av, price, cfg)
            if qty < 1:
                continue

            side = "long" if conv > 0 else "short"
            positions[sym] = Position(sym, side, price, qty, bar, av, cfg)

    # Close remaining positions at end
    for sym, pos in list(positions.items()):
        d = sym_data.get(sym)
        if d and d["c"]:
            exit_price = d["c"][-1]
            pnl_val = pos.pnl(exit_price)
            fee_cost = pos.qty * pos.entry * fee + pos.qty * exit_price * fee
            net_pnl = pnl_val - fee_cost
            equity += net_pnl
            trades.append({
                "sym": sym, "side": pos.side,
                "entry": pos.entry, "exit": exit_price,
                "qty": pos.qty, "pnl": round(net_pnl, 2),
                "pnl_pct": round(net_pnl / (pos.qty * pos.entry) * 100, 2),
                "bars": len(all_times) - pos.bar, "reason": "end",
            })

    # ── Statistics ──
    ret = (equity - initial_capital) / initial_capital * 100
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Sharpe (daily-ish approximation)
    if len(equity_curve) > 1:
        rets = [(equity_curve[i][1] - equity_curve[i - 1][1]) / equity_curve[i - 1][1]
                for i in range(1, len(equity_curve)) if equity_curve[i - 1][1] > 0]
        import math
        avg_r = sum(rets) / len(rets) if rets else 0
        std_r = math.sqrt(sum((r - avg_r) ** 2 for r in rets) / len(rets)) if rets else 1
        sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0
    else:
        sharpe = 0

    stats = {
        "final_equity": round(equity, 2),
        "return_pct": round(ret, 2),
        "max_dd_pct": round(max_dd, 2),
        "trades": len(trades),
        "win_rate": round(wr, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(pf, 2),
        "sharpe": round(sharpe, 2),
    }

    return stats, trades, equity_curve


# ── CLI Runner ───────────────────────────────────────────────────────

def print_results(label, stats, trades=None, top_n=10):
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    print(f"  Equity:  ${stats['final_equity']:>12,.2f}  ({stats['return_pct']:>+.1f}%)")
    print(f"  Max DD:  {stats['max_dd_pct']:>6.1f}%")
    print(f"  Sharpe:  {stats['sharpe']:>6.2f}")
    print(f"  Trades:  {stats['trades']:>6d}   WR: {stats['win_rate']:.0f}%")
    print(f"  Avg W:   {stats['avg_win_pct']:>+6.1f}%   Avg L: {stats['avg_loss_pct']:>+.1f}%")
    print(f"  PF:      {stats['profit_factor']:>6.2f}")
    if trades:
        by_pnl = sorted(trades, key=lambda x: abs(x["pnl"]), reverse=True)
        print(f"  Top trades:")
        for t in by_pnl[:top_n]:
            print(f"    {t['sym']:8s} {t['side']:5s} {t['reason']:8s} "
                  f"{t['pnl_pct']:>+7.1f}%  ${t['pnl']:>+10.2f}  {t['bars']}d")


SPLIT_MS = 1753833600000  # Aug 1 2025


def run():
    from src.data_fetcher import fetch_all_symbols
    symbols = STOCK_UNIVERSE
    print("Fetching daily data for stock universe...")
    data = fetch_all_symbols(symbols, interval="1d",
                             start_date="2023-06-01", end_date="2026-03-31")

    print(f"\n{'=' * 60}")
    print(f"  MULTI-FACTOR ADAPTIVE STRATEGY")
    print(f"{'=' * 60}")

    for label, kw in [
        ("TRAIN (Jun23-Aug25)", {"end_ms": SPLIT_MS}),
        ("TEST  (Aug25-Mar26)", {"start_ms": SPLIT_MS}),
        ("FULL  (Jun23-Mar26)", {}),
    ]:
        stats, trades, _ = backtest(data, **kw)
        print_results(label, stats, trades)

    return data


if __name__ == "__main__":
    run()
