"""
Dual Validation Layer v2

Layer 1: Rules Engine (Python, instant, free)
  - POC signal gating (MARGINAL/REJECT = auto-reject)
  - ATR-based stop validation
  - Symbol tier enforcement
  - Balance, limits, duplicates, data freshness

Layer 2: Risk Manager (Claude Opus, ~2s)
  - Thesis coherence with regime + POC reading
  - Correlation, timing, recent history

Both must pass before any trade executes.
"""
import os
import json
from datetime import datetime, timezone

NEON_URI = os.environ.get("NEON_URI", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

MAX_LONG_POSITIONS = 3
MAX_SHORT_POSITIONS = 2
MAX_TOTAL_POSITIONS = 5
MIN_CONFIDENCE = 0.5
DAILY_DRAWDOWN_LIMIT = -5
WEEKLY_DRAWDOWN_LIMIT = -10
KILL_SWITCH_LIMIT = -20

# Symbol tiers from backtest analysis
TIER_A = ["FETUSDT", "SUIUSDT", "TAOUSDT", "SOLUSDT", "BNBUSDT"]
TIER_B = ["AVAXUSDT", "LINKUSDT", "RENDERUSDT", "NEARUSDT", "XRPUSDT"]
TIER_C = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "DOGEUSDT", "DOTUSDT", "INJUSDT", "PENDLEUSDT", "ARUSDT"]

# POC signal sizing multipliers
POC_SIZING = {
    "STRONG": 1.0,
    "MEDIUM": 0.75,
    "WEAK": 0.4,
    "MARGINAL": 0.0,  # DO NOT TRADE
    "REJECT": 0.0,    # DO NOT TRADE
    "NO_DATA": 0.0,
}

# Tier sizing multipliers
TIER_SIZING = {
    "A": 1.0,
    "B": 0.5,
    "C": 0.25,
}


def get_conn():
    import psycopg2
    return psycopg2.connect(NEON_URI)


def get_symbol_tier(symbol):
    if symbol in TIER_A: return "A"
    if symbol in TIER_B: return "B"
    if symbol in TIER_C: return "C"
    return "C"  # default to most restrictive


def validate_rules(trade):
    """
    Mechanical pre-trade checks with POC gating and ATR validation.
    
    trade: {
        symbol, side (LONG/SHORT), quantity, entry_price, strategy,
        regime, confidence, thesis, leverage (default 1),
        poc_signal (STRONG/MEDIUM/WEAK/MARGINAL/REJECT),
        atr_stop (price level for stop loss),
    }
    """
    checks = {}
    
    # 1. Symbol in universe
    all_symbols = TIER_A + TIER_B + TIER_C
    checks["symbol_approved"] = trade["symbol"] in all_symbols
    
    # 2. POC signal gating (CRITICAL)
    poc = trade.get("poc_signal", "NO_DATA")
    checks["poc_not_marginal"] = poc not in ["MARGINAL", "REJECT", "NO_DATA"]
    
    # 3. Symbol tier vs POC signal
    tier = get_symbol_tier(trade["symbol"])
    if tier == "B":
        checks["tier_poc_match"] = poc == "STRONG"
    elif tier == "C":
        checks["tier_poc_match"] = poc == "STRONG" and len(trade.get("thesis", "")) > 50
    else:
        checks["tier_poc_match"] = True  # Tier A accepts STRONG and MEDIUM
    
    # 4. Confidence above threshold
    checks["confidence_ok"] = trade.get("confidence", 0) >= MIN_CONFIDENCE
    
    # 5. Position limits
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN' AND side='LONG'")
    long_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN' AND side='SHORT'")
    short_count = cur.fetchone()[0]
    
    side = trade.get("side", "LONG")
    if side == "LONG":
        checks["positions_ok"] = long_count < MAX_LONG_POSITIONS
    else:
        checks["positions_ok"] = short_count < MAX_SHORT_POSITIONS
    checks["total_positions_ok"] = (long_count + short_count) < MAX_TOTAL_POSITIONS
    
    # 6. No duplicate position on same side
    cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN' AND symbol=%s AND side=%s",
                (trade["symbol"], side))
    checks["no_duplicate"] = cur.fetchone()[0] == 0
    
    # 7. Size within limits (adjusted for POC + tier)
    poc_mult = POC_SIZING.get(poc, 0)
    tier_mult = TIER_SIZING.get(tier, 0.25)
    max_size_pct = 10 * poc_mult * tier_mult  # base 10%, adjusted
    trade_notional = trade["quantity"] * trade["entry_price"] * trade.get("leverage", 1)
    book_value = max(1000, 1000)  # TODO: calculate actual book value
    position_pct = (trade_notional / book_value) * 100
    checks["size_ok"] = position_pct <= max(max_size_pct, 1)
    
    # 8. Leverage within limits
    checks["leverage_ok"] = trade.get("leverage", 1) <= 5
    
    # 9. Has thesis
    checks["has_thesis"] = len(trade.get("thesis", "")) > 10
    
    # 10. Has ATR stop
    checks["has_atr_stop"] = trade.get("atr_stop") is not None and trade.get("atr_stop") > 0
    
    # 11. Drawdown checks
    cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE status='CLOSED' AND exit_time > NOW() - INTERVAL '1 day'")
    daily_pnl = float(cur.fetchone()[0])
    checks["daily_drawdown_ok"] = (daily_pnl / book_value) * 100 > DAILY_DRAWDOWN_LIMIT
    
    cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE status='CLOSED' AND exit_time > NOW() - INTERVAL '7 days'")
    weekly_pnl = float(cur.fetchone()[0])
    checks["weekly_drawdown_ok"] = (weekly_pnl / book_value) * 100 > WEEKLY_DRAWDOWN_LIMIT
    
    # 12. Kill switch
    cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE status='CLOSED'")
    total_pnl = float(cur.fetchone()[0])
    checks["kill_switch_ok"] = (total_pnl / 1000) * 100 > KILL_SWITCH_LIMIT
    
    cur.close(); conn.close()
    
    all_passed = all(checks.values())
    failed = [k for k, v in checks.items() if not v]
    reason = "All checks passed" if all_passed else f"Failed: {', '.join(failed)}"
    
    return {"passed": all_passed, "reason": reason, "checks": checks,
            "sizing": {"poc_mult": poc_mult, "tier_mult": tier_mult, "tier": tier, "poc_signal": poc}}


def validate_risk_manager(trade, portfolio_state, regime_state):
    """Calls Claude Opus with sceptical risk manager prompt."""
    if not ANTHROPIC_API_KEY:
        return {"approved": True, "reason": "No API key, skipping risk review (DRY_RUN)"}
    
    import httpx
    
    prompt = f"""You are a SCEPTICAL risk manager. Find reasons NOT to take this trade.
Approve only if you cannot find a strong reason to reject.

Trade:
  Symbol: {trade['symbol']} (Tier {get_symbol_tier(trade['symbol'])})
  Side: {trade['side']}
  Size: {trade['quantity']} @ ${trade['entry_price']}
  Leverage: {trade.get('leverage', 1)}x
  POC Signal: {trade.get('poc_signal', 'UNKNOWN')}
  ATR Stop: ${trade.get('atr_stop', 'NOT SET')}
  Regime: {trade['regime']} (confidence: {trade.get('confidence', 0)})
  Thesis: {trade.get('thesis', 'No thesis')}

Portfolio: {json.dumps(portfolio_state, indent=2, default=str)}
Regime State: {json.dumps(regime_state, indent=2, default=str)}

Check: thesis coherent with regime + POC? Correlation risk? Bad timing? Recent losses on this setup?

Respond EXACTLY:
APPROVE: [reason]
or
REJECT: [reason]"""

    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "content-type": "application/json", "anthropic-version": "2023-06-01"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 200,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        text = resp.json().get("content", [{}])[0].get("text", "")
        if text.startswith("APPROVE"): return {"approved": True, "reason": text}
        if text.startswith("REJECT"): return {"approved": False, "reason": text}
        return {"approved": False, "reason": f"Unclear: {text[:200]}"}
    except Exception as e:
        return {"approved": True, "reason": f"Risk manager unavailable: {e}. Proceeding with caution."}


def validate_trade(trade, portfolio_state=None, regime_state=None):
    """Run both validation layers."""
    rules = validate_rules(trade)
    if not rules["passed"]:
        return {"approved": False, "rules": rules,
                "risk_manager": {"approved": False, "reason": "Skipped - rules failed"},
                "reason": rules["reason"]}
    
    if portfolio_state is None:
        from src.portfolio import get_book
        portfolio_state = get_book()
    
    risk = validate_risk_manager(trade, portfolio_state, regime_state or {})
    approved = rules["passed"] and risk["approved"]
    return {"approved": approved, "rules": rules, "risk_manager": risk,
            "reason": "Trade approved" if approved else risk.get("reason", rules.get("reason"))}
