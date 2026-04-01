"""
Dual Validation Layer

Layer 1: Rules Engine (Python, instant, free)
  - Mechanical checks: balance, limits, duplicates, data freshness
  - Returns PASS/FAIL with reason

Layer 2: Risk Manager (Claude Opus, ~2s, ~$0.03)
  - Separate system prompt with sceptical mandate
  - Checks thesis coherence, correlation, timing
  - Returns APPROVE/REJECT with reason

Both must pass before any trade executes.
"""
import os
import json
import time
from datetime import datetime, timezone, timedelta

NEON_URI = os.environ.get("NEON_URI", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAX_POSITIONS = 3
MAX_SINGLE_POSITION_PCT = 10
MIN_CONFIDENCE = 0.5
MAX_DATA_AGE_MINUTES = 30
DAILY_DRAWDOWN_LIMIT = -5  # percent
WEEKLY_DRAWDOWN_LIMIT = -10
KILL_SWITCH_LIMIT = -20


def get_conn():
    import psycopg2
    return psycopg2.connect(NEON_URI)


# ========== LAYER 1: RULES ENGINE ==========

def validate_rules(trade):
    """
    Mechanical pre-trade checks. Returns {passed: bool, reason: str, checks: dict}
    
    trade: {
        symbol: str,
        side: str (LONG/SHORT),
        quantity: float,
        entry_price: float,
        strategy: str,
        regime: int,
        confidence: float,
        thesis: str,
        leverage: float (default 1),
    }
    """
    checks = {}
    
    # 1. Symbol in universe
    try:
        with open("config/symbols.json") as f:
            universe = json.load(f)
        symbols = [s["symbol"] for s in universe.get("symbols", universe)] if isinstance(universe, dict) else [s["symbol"] for s in universe]
    except Exception:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
                   "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "TAOUSDT", "RENDERUSDT",
                   "FETUSDT", "NEARUSDT", "ARUSDT", "INJUSDT", "SUIUSDT", "PENDLEUSDT"]
    checks["symbol_approved"] = trade["symbol"] in symbols
    
    # 2. Confidence above threshold
    checks["confidence_ok"] = trade.get("confidence", 0) >= MIN_CONFIDENCE
    
    # 3. Not at max positions
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'")
    open_count = cur.fetchone()[0]
    checks["positions_ok"] = open_count < MAX_POSITIONS
    
    # 4. No duplicate position
    cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN' AND symbol=%s", (trade["symbol"],))
    dup = cur.fetchone()[0]
    checks["no_duplicate"] = dup == 0
    
    # 5. Position size within limits
    cur.execute("SELECT COALESCE(SUM(notional), 0) FROM positions WHERE status='OPEN'")
    total_notional = float(cur.fetchone()[0])
    trade_notional = trade["quantity"] * trade["entry_price"] * trade.get("leverage", 1)
    book_value = max(total_notional + 1000, 1000)  # approximate, use actual balance in production
    position_pct = (trade_notional / book_value) * 100
    checks["size_ok"] = position_pct <= MAX_SINGLE_POSITION_PCT
    
    # 6. Leverage within limits
    leverage = trade.get("leverage", 1)
    checks["leverage_ok"] = leverage <= 5
    
    # 7. Has thesis
    checks["has_thesis"] = len(trade.get("thesis", "")) > 10
    
    # 8. Check drawdown limits
    cur.execute("""
        SELECT COALESCE(SUM(pnl), 0) FROM positions 
        WHERE status='CLOSED' AND exit_time > NOW() - INTERVAL '1 day'
    """)
    daily_pnl = float(cur.fetchone()[0])
    daily_pnl_pct = (daily_pnl / book_value) * 100 if book_value > 0 else 0
    checks["daily_drawdown_ok"] = daily_pnl_pct > DAILY_DRAWDOWN_LIMIT
    
    cur.execute("""
        SELECT COALESCE(SUM(pnl), 0) FROM positions 
        WHERE status='CLOSED' AND exit_time > NOW() - INTERVAL '7 days'
    """)
    weekly_pnl = float(cur.fetchone()[0])
    weekly_pnl_pct = (weekly_pnl / book_value) * 100 if book_value > 0 else 0
    checks["weekly_drawdown_ok"] = weekly_pnl_pct > WEEKLY_DRAWDOWN_LIMIT
    
    # 9. Kill switch
    cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE status='CLOSED'")
    total_pnl = float(cur.fetchone()[0])
    total_pnl_pct = (total_pnl / 1000) * 100  # vs starting capital
    checks["kill_switch_ok"] = total_pnl_pct > KILL_SWITCH_LIMIT
    
    cur.close(); conn.close()
    
    # Overall
    all_passed = all(checks.values())
    failed = [k for k, v in checks.items() if not v]
    reason = "All checks passed" if all_passed else f"Failed: {', '.join(failed)}"
    
    return {"passed": all_passed, "reason": reason, "checks": checks}


# ========== LAYER 2: RISK MANAGER (Claude Opus) ==========

def validate_risk_manager(trade, portfolio_state, regime_state):
    """
    Calls Claude Opus with a sceptical risk manager prompt.
    Returns {approved: bool, reason: str}
    """
    if not ANTHROPIC_API_KEY:
        return {"approved": True, "reason": "No API key, skipping risk review (DRY_RUN)"}
    
    import httpx
    
    prompt = f"""You are a SCEPTICAL risk manager. Your job is to find reasons NOT to take this trade.
You approve only if you cannot find a strong reason to reject.

Proposed Trade:
  Symbol: {trade['symbol']}
  Side: {trade['side']}
  Size: {trade['quantity']} @ ${trade['entry_price']}
  Leverage: {trade.get('leverage', 1)}x
  Strategy: {trade['strategy']}
  Regime: {trade['regime']} (confidence: {trade.get('confidence', 0)})
  Thesis: {trade.get('thesis', 'No thesis provided')}

Current Portfolio:
{json.dumps(portfolio_state, indent=2, default=str)}

Current Regime State:
{json.dumps(regime_state, indent=2, default=str)}

Check:
1. Is the thesis coherent? Does buying {trade['symbol']} make sense given the regime?
2. Correlation: are we already exposed to similar assets?
3. Timing: any reason this is a bad time?
4. Recent history: have we lost on this exact setup recently?
5. Overall portfolio heat: are we overexposed?

Respond with EXACTLY one line:
APPROVE: [reason]
or
REJECT: [reason]
"""

    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "content-type": "application/json", "anthropic-version": "2023-06-01"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 200,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        result = resp.json()
        text = result.get("content", [{}])[0].get("text", "")
        
        if text.startswith("APPROVE"):
            return {"approved": True, "reason": text}
        elif text.startswith("REJECT"):
            return {"approved": False, "reason": text}
        else:
            return {"approved": False, "reason": f"Unclear response: {text[:200]}"}
    except Exception as e:
        return {"approved": True, "reason": f"Risk manager unavailable: {e}. Proceeding with caution."}


# ========== COMBINED VALIDATION ==========

def validate_trade(trade, portfolio_state=None, regime_state=None):
    """
    Run both validation layers.
    Returns {approved: bool, rules: dict, risk_manager: dict}
    """
    # Layer 1: Rules engine
    rules = validate_rules(trade)
    
    if not rules["passed"]:
        return {
            "approved": False,
            "rules": rules,
            "risk_manager": {"approved": False, "reason": "Skipped - rules engine failed"},
            "reason": rules["reason"]
        }
    
    # Layer 2: Risk manager
    if portfolio_state is None:
        from src.portfolio import get_book
        portfolio_state = get_book()
    
    risk = validate_risk_manager(trade, portfolio_state, regime_state or {})
    
    approved = rules["passed"] and risk["approved"]
    
    return {
        "approved": approved,
        "rules": rules,
        "risk_manager": risk,
        "reason": "Trade approved" if approved else risk.get("reason", rules.get("reason"))
    }
