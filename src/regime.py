"""7-state regime classifier."""
import math

REGIMES = [
    {"id": 0, "name": "Strong Bull", "action": "Aggressive Long", "leverage": 2.5},
    {"id": 1, "name": "Bull", "action": "Long", "leverage": 1.5},
    {"id": 2, "name": "Weak Bull", "action": "Cautious Long", "leverage": 1.0},
    {"id": 3, "name": "Neutral", "action": "Flat", "leverage": 0.5},
    {"id": 4, "name": "Weak Bear", "action": "Cautious Short", "leverage": 1.0},
    {"id": 5, "name": "Bear", "action": "Short", "leverage": 1.5},
    {"id": 6, "name": "Crash", "action": "Max Short / Hedge", "leverage": 2.5},
]

def classify(closes, volumes, idx, window=14):
    if idx < window:
        return 3, 0.5
    rets = [(closes[j] - closes[j-1]) / closes[j-1] for j in range(max(1, idx - window + 1), idx + 1) if closes[j-1] > 0]
    if not rets:
        return 3, 0.5
    avg_ret = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - avg_ret)**2 for r in rets) / len(rets)) if len(rets) > 1 else 0
    avg_vol = sum(volumes[max(0, idx - window):idx + 1]) / min(window + 1, idx + 1)
    vol_ratio = volumes[idx] / avg_vol if avg_vol > 0 else 1
    score = avg_ret * 10000
    if vol > 0.03:
        score -= 2
    if vol_ratio > 2:
        score += 1 if score > 0 else -1
    if score > 3: return 0, min(0.95, 0.6 + score * 0.03)
    if score > 1.5: return 1, min(0.97, 0.55 + score * 0.05)
    if score > 0.3: return 2, min(0.97, 0.5 + score * 0.08)
    if score > -0.3: return 3, min(0.97, 0.4 + abs(score) * 0.1)
    if score > -1.5: return 4, min(0.97, 0.5 + abs(score) * 0.08)
    if score > -3: return 5, min(0.97, 0.55 + abs(score) * 0.05)
    return 6, min(0.95, 0.6 + abs(score) * 0.03)

def classify_bulk(candles):
    closes = [c[4] for c in candles]
    volumes = [c[5] for c in candles]
    return [classify(closes, volumes, i) for i in range(len(candles))]
