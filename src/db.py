"""Database connection layer for Neon PostgreSQL."""
import os
import psycopg2
from contextlib import contextmanager

NEON_URI = os.environ.get("NEON_URI", os.environ.get("DATABASE_URL", ""))

@contextmanager
def get_conn():
    conn = psycopg2.connect(NEON_URI)
    try:
        yield conn
    finally:
        conn.close()

def get_candles(symbol, interval="1m", limit=None, start_time=None, end_time=None):
    query = "SELECT open_time, open, high, low, close, volume, regime, confidence FROM candles WHERE symbol=%s AND interval=%s"
    params = [symbol, interval]
    if start_time:
        query += " AND open_time >= %s"
        params.append(start_time)
    if end_time:
        query += " AND open_time < %s"
        params.append(end_time)
    query += " ORDER BY open_time"
    if limit:
        query += " LIMIT %s"
        params.append(limit)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
    return rows

def get_strategies(enabled_only=True):
    query = "SELECT strategy_id, name, type, enabled, params_json FROM strategies"
    if enabled_only:
        query += " WHERE enabled=TRUE"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
    return [{"id": r[0], "name": r[1], "type": r[2], "enabled": r[3], "params": r[4]} for r in rows]

def count_candles():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT symbol, COUNT(*) FROM candles GROUP BY symbol ORDER BY symbol")
        result = {r[0]: r[1] for r in cur.fetchall()}
        cur.close()
    return result
