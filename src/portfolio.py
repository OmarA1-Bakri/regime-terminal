"""
Portfolio Management — Claude-operated investment book

This module manages all positions, P&L tracking, and allocation
enforcement for the Regime Terminal. Designed for autonomous
operation by Claude Code or Claude workflows.

DB Tables:
- positions: Individual trades with entry/exit, P&L, strategy tags
- allocations: Target % per strategy with risk limits
- trade_log: Audit trail of every action taken

Strategies: 'regime' (HMM crypto), 'tao' (Bittensor staking), 'manual'
"""
import os
import json
from datetime import datetime, timezone
from decimal import Decimal

NEON_URI = os.environ.get("NEON_URI", os.environ.get("DATABASE_URL", ""))

def _conn():
    import psycopg2
    return psycopg2.connect(NEON_URI)


def get_book():
    """Get all open positions with current P&L."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, side, strategy, entry_price, quantity, notional,
               regime_at_entry, confidence_at_entry, entry_time, notes
        FROM positions WHERE status='OPEN' ORDER BY entry_time DESC
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{
        "id": r[0], "symbol": r[1], "side": r[2], "strategy": r[3],
        "entry_price": float(r[4]), "quantity": float(r[5]),
        "notional": float(r[6]), "regime_at_entry": r[7],
        "confidence_at_entry": float(r[8]) if r[8] else None,
        "entry_time": r[9].isoformat() if r[9] else None,
        "notes": r[10]
    } for r in rows]


def open_position(symbol, side, quantity, entry_price, strategy,
                  regime=None, confidence=None, notes=None, execute=True):
    """Open a new position.

    Args:
        symbol: Trading pair e.g. BTCUSDT
        side: LONG or SHORT
        quantity: Amount of base asset
        entry_price: Price at entry
        strategy: regime | tao | manual
        regime: Current regime state (0-6)
        confidence: Regime confidence (0-1)
        notes: Free text notes
        execute: If True, also place order on Binance testnet
    """
    notional = float(quantity) * float(entry_price)

    # Check allocation limits
    limits = get_allocations()
    strategy_alloc = next((a for a in limits if a["strategy"] == strategy), None)
    if strategy_alloc:
        if not strategy_alloc["enabled"]:
            return {"error": f"Strategy '{strategy}' is disabled"}
        open_positions = [p for p in get_book() if p["strategy"] == strategy]
        if len(open_positions) >= strategy_alloc["max_positions"]:
            return {"error": f"Max positions ({strategy_alloc['max_positions']}) reached for '{strategy}'"}

    conn = _conn(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO positions (symbol, side, strategy, entry_price, quantity, notional,
                              regime_at_entry, confidence_at_entry, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, entry_time
    """, (symbol.upper(), side.upper(), strategy, entry_price, quantity, notional,
          regime, confidence, notes))
    pos_id, entry_time = cur.fetchone()

    cur.execute("""
        INSERT INTO trade_log (position_id, action, symbol, side, quantity, price, strategy, mode)
        VALUES (%s, 'OPEN', %s, %s, %s, %s, %s, %s)
    """, (pos_id, symbol.upper(), side.upper(), quantity, entry_price, strategy,
          os.environ.get("DRY_RUN", "true") == "true" and "DRY_RUN" or
          (os.environ.get("USE_TESTNET", "true") == "true" and "TESTNET" or "LIVE")))
    conn.commit()
    cur.close(); conn.close()

    result = {
        "position_id": pos_id,
        "symbol": symbol.upper(),
        "side": side.upper(),
        "strategy": strategy,
        "quantity": float(quantity),
        "entry_price": float(entry_price),
        "notional": notional,
        "entry_time": entry_time.isoformat() if entry_time else None,
    }

    # Execute on Binance if requested
    if execute:
        try:
            from src.paper_trade import place_order
            order_side = "BUY" if side.upper() == "LONG" else "SELL"
            execution = place_order(symbol.upper(), order_side, quantity)
            result["execution"] = execution
        except Exception as e:
            result["execution_error"] = str(e)

    return result


def close_position(position_id, exit_price, notes=None, execute=True):
    """Close an open position and calculate P&L.

    Args:
        position_id: ID from positions table
        exit_price: Price at exit
        notes: Free text notes
        execute: If True, also place closing order on Binance testnet
    """
    conn = _conn(); cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, side, strategy, entry_price, quantity, notional, status
        FROM positions WHERE id=%s
    """, (position_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return {"error": f"Position {position_id} not found"}
    if row[7] == "CLOSED":
        cur.close(); conn.close()
        return {"error": f"Position {position_id} already closed"}

    pos_id, symbol, side, strategy, entry_price, quantity, notional, _ = row
    entry_price = float(entry_price)
    exit_price = float(exit_price)
    quantity = float(quantity)

    if side == "LONG":
        pnl = (exit_price - entry_price) * quantity
    else:
        pnl = (entry_price - exit_price) * quantity
    pnl_pct = (pnl / float(notional)) * 100 if notional else 0

    cur.execute("""
        UPDATE positions SET status='CLOSED', exit_price=%s, exit_time=NOW(),
               pnl=%s, pnl_pct=%s, notes=COALESCE(notes||' | '||%s, notes)
        WHERE id=%s
    """, (exit_price, round(pnl, 4), round(pnl_pct, 4), notes, pos_id))

    mode = "DRY_RUN" if os.environ.get("DRY_RUN", "true") == "true" else (
        "TESTNET" if os.environ.get("USE_TESTNET", "true") == "true" else "LIVE")
    cur.execute("""
        INSERT INTO trade_log (position_id, action, symbol, side, quantity, price, strategy, mode)
        VALUES (%s, 'CLOSE', %s, %s, %s, %s, %s, %s)
    """, (pos_id, symbol, "SELL" if side == "LONG" else "BUY", quantity, exit_price, strategy, mode))
    conn.commit()
    cur.close(); conn.close()

    result = {
        "position_id": pos_id,
        "symbol": symbol,
        "side": side,
        "strategy": strategy,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 4),
    }

    if execute:
        try:
            from src.paper_trade import place_order
            close_side = "SELL" if side == "LONG" else "BUY"
            execution = place_order(symbol, close_side, quantity)
            result["execution"] = execution
        except Exception as e:
            result["execution_error"] = str(e)

    return result


def get_pnl(strategy=None):
    """Get P&L summary — realised (closed) + unrealised (open)."""
    conn = _conn(); cur = conn.cursor()

    # Realised P&L from closed positions
    q = "SELECT strategy, COUNT(*), SUM(pnl), AVG(pnl_pct) FROM positions WHERE status='CLOSED'"
    params = []
    if strategy:
        q += " AND strategy=%s"
        params.append(strategy)
    q += " GROUP BY strategy"
    cur.execute(q, params)
    realised = {}
    for strat, count, total_pnl, avg_pct in cur.fetchall():
        realised[strat] = {
            "closed_trades": count,
            "total_pnl": float(total_pnl) if total_pnl else 0,
            "avg_pnl_pct": float(avg_pct) if avg_pct else 0,
        }

    # Open positions (unrealised)
    q = "SELECT id, symbol, side, strategy, entry_price, quantity, notional FROM positions WHERE status='OPEN'"
    params = []
    if strategy:
        q += " AND strategy=%s"
        params.append(strategy)
    cur.execute(q, params)
    open_positions = cur.fetchall()
    cur.close(); conn.close()

    unrealised = []
    for pos_id, symbol, side, strat, ep, qty, notional in open_positions:
        unrealised.append({
            "id": pos_id, "symbol": symbol, "side": side, "strategy": strat,
            "entry_price": float(ep), "quantity": float(qty), "notional": float(notional),
            "note": "Fetch current price to calculate unrealised P&L"
        })

    return {"realised": realised, "unrealised": unrealised, "open_count": len(unrealised)}


def get_allocations():
    """Get target vs actual allocation per strategy."""
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT strategy, target_pct, max_position_pct, max_positions, enabled FROM allocations ORDER BY strategy")
    allocs = cur.fetchall()

    cur.execute("""
        SELECT strategy, COUNT(*), SUM(notional)
        FROM positions WHERE status='OPEN' GROUP BY strategy
    """)
    actuals = {r[0]: {"count": r[1], "notional": float(r[2]) if r[2] else 0} for r in cur.fetchall()}
    cur.close(); conn.close()

    total_notional = sum(a["notional"] for a in actuals.values())
    result = []
    for strat, target, max_pos, max_n, enabled in allocs:
        actual = actuals.get(strat, {"count": 0, "notional": 0})
        actual_pct = (actual["notional"] / total_notional * 100) if total_notional > 0 else 0
        result.append({
            "strategy": strat,
            "target_pct": float(target),
            "actual_pct": round(actual_pct, 2),
            "drift": round(actual_pct - float(target), 2),
            "open_positions": actual["count"],
            "max_positions": max_n,
            "max_position_pct": float(max_pos),
            "enabled": enabled,
        })
    return result


def get_trade_history(limit=50, strategy=None):
    """Get recent trade history from the audit log."""
    conn = _conn(); cur = conn.cursor()
    q = "SELECT id, position_id, action, symbol, side, quantity, price, strategy, mode, executed_at FROM trade_log"
    params = []
    if strategy:
        q += " WHERE strategy=%s"
        params.append(strategy)
    q += " ORDER BY executed_at DESC LIMIT %s"
    params.append(limit)
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{
        "id": r[0], "position_id": r[1], "action": r[2], "symbol": r[3],
        "side": r[4], "quantity": float(r[5]), "price": float(r[6]),
        "strategy": r[7], "mode": r[8], "executed_at": r[9].isoformat() if r[9] else None
    } for r in rows]


def update_allocation(strategy, target_pct=None, max_position_pct=None, max_positions=None, enabled=None):
    """Update allocation rules for a strategy."""
    conn = _conn(); cur = conn.cursor()
    updates = []
    params = []
    if target_pct is not None:
        updates.append("target_pct=%s"); params.append(target_pct)
    if max_position_pct is not None:
        updates.append("max_position_pct=%s"); params.append(max_position_pct)
    if max_positions is not None:
        updates.append("max_positions=%s"); params.append(max_positions)
    if enabled is not None:
        updates.append("enabled=%s"); params.append(enabled)
    if not updates:
        return {"error": "No updates provided"}
    updates.append("updated_at=NOW()")
    params.append(strategy)
    cur.execute(f"UPDATE allocations SET {', '.join(updates)} WHERE strategy=%s", params)
    conn.commit()
    cur.close(); conn.close()
    return {"strategy": strategy, "updated": True}
