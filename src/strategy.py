"""
STRATEGY FILE — The autoresearch agent modifies THIS file.
This is the 'train.py' equivalent from Karpathy's autoresearch.
"""
from src.regime import REGIMES

BULLISH_REGIMES = {0, 1, 2}
BEARISH_REGIMES = {4, 5, 6}
MIN_CONFIDENCE = 0.55
COOLDOWN_BARS = 48 * 60
MIN_HOLD_BARS = 12 * 60
LEVERAGE_MAP = {0: 2.5, 1: 1.5, 2: 1.0, 3: 0.5, 4: 1.0, 5: 1.5, 6: 2.5}


def strategy_fn(candle, regime, confidence, state):
    if "bars_since_exit" not in state:
        state["bars_since_exit"] = COOLDOWN_BARS + 1
        state["bars_in_position"] = 0
        state["position_side"] = None

    state["bars_since_exit"] += 1

    if state["position_side"] is not None:
        state["bars_in_position"] += 1
        should_exit = False
        if state["position_side"] == "LONG" and regime in BEARISH_REGIMES:
            should_exit = True
        elif state["position_side"] == "SHORT" and regime in BULLISH_REGIMES:
            should_exit = True
        if state["bars_in_position"] < MIN_HOLD_BARS:
            should_exit = False
        if should_exit:
            state["position_side"] = None
            state["bars_in_position"] = 0
            state["bars_since_exit"] = 0
            return {"action": "EXIT"}
        return {"action": "HOLD"}

    if state["bars_since_exit"] < COOLDOWN_BARS:
        return {"action": "HOLD"}
    if confidence < MIN_CONFIDENCE:
        return {"action": "HOLD"}

    if regime in BULLISH_REGIMES:
        state["position_side"] = "LONG"
        state["bars_in_position"] = 0
        return {"action": "ENTER", "side": "LONG", "leverage": LEVERAGE_MAP.get(regime, 1.0)}
    if regime in BEARISH_REGIMES:
        state["position_side"] = "SHORT"
        state["bars_in_position"] = 0
        return {"action": "ENTER", "side": "SHORT", "leverage": LEVERAGE_MAP.get(regime, 1.0)}

    return {"action": "HOLD"}
