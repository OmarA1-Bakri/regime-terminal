"""
Multi-Timeframe Gaussian HMM Regime Classifier

Trains separate HMMs for 1-minute, 1-hour, and 4-hour timeframes.
- 1m: Execution timing (when to enter/exit)
- 1h: Signal confirmation (is the transition real?)
- 4h: Regime detection (primary trading decisions)

Each timeframe has its own model, scaler, and state map.
Baum-Welch for training, Viterbi for inference, StandardScaler for normalization.
"""
import os
import math
import json
import pickle
import numpy as np
from pathlib import Path

try:
    from hmmlearn.hmm import GaussianHMM
except ImportError:
    GaussianHMM = None

try:
    from sklearn.preprocessing import StandardScaler
except ImportError:
    StandardScaler = None

N_STATES = 7
WINDOW = 14
MODEL_DIR = Path(__file__).parent.parent / "models"
VALID_TIMEFRAMES = ["1m", "1h", "4h"]

REGIMES = [
    {"id": 0, "name": "Strong Bull", "action": "Aggressive Long"},
    {"id": 1, "name": "Bull", "action": "Long"},
    {"id": 2, "name": "Weak Bull", "action": "Cautious Long"},
    {"id": 3, "name": "Neutral", "action": "Flat"},
    {"id": 4, "name": "Weak Bear", "action": "Cautious Short"},
    {"id": 5, "name": "Bear", "action": "Short"},
    {"id": 6, "name": "Crash", "action": "Max Short / Hedge"},
]


def _model_paths(timeframe="1m"):
    return (
        MODEL_DIR / f"hmm_regime_{timeframe}.pkl",
        MODEL_DIR / f"hmm_scaler_{timeframe}.pkl",
        MODEL_DIR / f"hmm_state_map_{timeframe}.json",
    )


def _compute_features_raw(closes, volumes, window=WINDOW):
    n = len(closes)
    if n < window + 1:
        return None, 0
    feats = []
    for i in range(window, n):
        rets = [math.log(closes[j] / closes[j - 1])
                for j in range(i - window + 1, i + 1) if closes[j - 1] > 0]
        if not rets:
            rets = [0.0]
        avg_ret = sum(rets) / len(rets)
        vol = math.sqrt(sum((r - avg_ret) ** 2 for r in rets) / max(len(rets) - 1, 1))
        avg_vol = sum(volumes[max(0, i - window):i + 1]) / min(window + 1, i + 1)
        vol_ratio = volumes[i] / avg_vol if avg_vol > 0 else 1.0
        feats.append([avg_ret, vol, vol_ratio])
    return np.array(feats), window


def train(closes, volumes, n_states=N_STATES, window=WINDOW, max_iter=200):
    if GaussianHMM is None:
        raise ImportError("hmmlearn not installed")
    if StandardScaler is None:
        raise ImportError("scikit-learn not installed")
    X_raw, _ = _compute_features_raw(closes, volumes, window)
    if X_raw is None or len(X_raw) < 100:
        raise ValueError(f"Not enough data. Got {len(closes)} candles, need {window + 100}+")
    scaler = StandardScaler()
    X = scaler.fit_transform(X_raw)
    model = GaussianHMM(n_components=n_states, covariance_type="diag",
                        n_iter=max_iter, random_state=42, min_covar=1e-3, tol=1e-4)
    model.fit(X)
    mean_returns = model.means_[:, 0]
    sorted_indices = np.argsort(-mean_returns)
    state_map = {int(raw): regime_id for regime_id, raw in enumerate(sorted_indices)}
    return model, scaler, state_map


def save_model(model, scaler, state_map, timeframe="1m"):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    mp, sp, smp = _model_paths(timeframe)
    with open(mp, "wb") as f: pickle.dump(model, f)
    with open(sp, "wb") as f: pickle.dump(scaler, f)
    with open(smp, "w") as f: json.dump(state_map, f)
    return str(mp)


def load_model(timeframe="1m"):
    mp, sp, smp = _model_paths(timeframe)
    with open(mp, "rb") as f: model = pickle.load(f)
    with open(sp, "rb") as f: scaler = pickle.load(f)
    with open(smp, "r") as f: state_map = {int(k): v for k, v in json.load(f).items()}
    return model, scaler, state_map


def classify(closes, volumes, idx, window=WINDOW, model=None, scaler=None, state_map=None, timeframe="1m"):
    if idx < window:
        return 3, 0.5
    if model is None or scaler is None or state_map is None:
        try:
            model, scaler, state_map = load_model(timeframe)
        except (FileNotFoundError, Exception):
            return _classify_deterministic(closes, volumes, idx, window)
    start = max(0, idx - window * 2)
    X_raw, _ = _compute_features_raw(closes[start:idx + 1], volumes[start:idx + 1], window)
    if X_raw is None or len(X_raw) == 0:
        return 3, 0.5
    X = scaler.transform(X_raw)
    _, state_seq = model.decode(X, algorithm="viterbi")
    raw_state = state_seq[-1]
    regime_id = state_map.get(raw_state, 3)
    posteriors = model.predict_proba(X)
    confidence = float(posteriors[-1, raw_state])
    return regime_id, round(confidence, 3)


def classify_sequence(closes, volumes, model=None, scaler=None, state_map=None, window=WINDOW, timeframe="1m"):
    if model is None or scaler is None or state_map is None:
        try:
            model, scaler, state_map = load_model(timeframe)
        except (FileNotFoundError, Exception):
            return [_classify_deterministic(closes, volumes, i, window) for i in range(len(closes))]
    X_raw, valid_start = _compute_features_raw(closes, volumes, window)
    if X_raw is None:
        return [(3, 0.5)] * len(closes)
    X = scaler.transform(X_raw)
    _, state_seq = model.decode(X, algorithm="viterbi")
    posteriors = model.predict_proba(X)
    results = [(3, 0.5)] * valid_start
    for i, raw_state in enumerate(state_seq):
        regime_id = state_map.get(int(raw_state), 3)
        confidence = float(posteriors[i, raw_state])
        results.append((regime_id, round(confidence, 3)))
    return results


def get_transition_matrix(model=None, state_map=None, timeframe="1m"):
    if model is None or state_map is None:
        model, _, state_map = load_model(timeframe)
    raw = model.transmat_
    n = raw.shape[0]
    ordered = np.zeros((n, n))
    inv_map = {v: k for k, v in state_map.items()}
    for fr in range(n):
        for to in range(n):
            ordered[fr, to] = raw[inv_map[fr], inv_map[to]]
    return {"timeframe": timeframe, "matrix": [[round(p, 4) for p in row] for row in ordered.tolist()],
            "labels": [r["name"] for r in REGIMES]}


def get_state_characteristics(model=None, scaler=None, state_map=None, timeframe="1m"):
    if model is None or scaler is None or state_map is None:
        model, scaler, state_map = load_model(timeframe)
    inv_map = {v: k for k, v in state_map.items()}
    names = ["log_return", "realised_vol", "volume_ratio"]
    states = {}
    for rid in range(N_STATES):
        raw = inv_map[rid]
        orig_means = model.means_[raw] * scaler.scale_ + scaler.mean_
        states[REGIMES[rid]["name"]] = {
            "regime_id": rid,
            "means": {n: round(float(m), 8) for n, m in zip(names, orig_means)},
        }
    return {"timeframe": timeframe, "states": states}


def _classify_deterministic(closes, volumes, idx, window=WINDOW):
    if idx < window:
        return 3, 0.5
    rets = [(closes[j] - closes[j-1]) / closes[j-1]
            for j in range(max(1, idx - window + 1), idx + 1) if closes[j-1] > 0]
    if not rets:
        return 3, 0.5
    avg_ret = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - avg_ret)**2 for r in rets) / len(rets)) if len(rets) > 1 else 0
    avg_vol = sum(volumes[max(0, idx - window):idx + 1]) / min(window + 1, idx + 1)
    vol_ratio = volumes[idx] / avg_vol if avg_vol > 0 else 1
    score = avg_ret * 10000
    if vol > 0.03: score -= 2
    if vol_ratio > 2: score += 1 if score > 0 else -1
    if score > 3: return 0, min(0.95, 0.6 + score * 0.03)
    if score > 1.5: return 1, min(0.97, 0.55 + score * 0.05)
    if score > 0.3: return 2, min(0.97, 0.5 + score * 0.08)
    if score > -0.3: return 3, min(0.97, 0.4 + abs(score) * 0.1)
    if score > -1.5: return 4, min(0.97, 0.5 + abs(score) * 0.08)
    if score > -3: return 5, min(0.97, 0.55 + abs(score) * 0.05)
    return 6, min(0.95, 0.6 + abs(score) * 0.03)


def train_from_db(symbol="BTCUSDT", neon_uri=None, limit=50000, timeframe="1m"):
    import psycopg2
    if neon_uri is None:
        neon_uri = os.environ.get("NEON_URI", "")
    conn = psycopg2.connect(neon_uri)
    cur = conn.cursor()
    table = {"1m": "candles", "1h": "candles_1h", "4h": "candles_4h"}.get(timeframe, "candles")
    if symbol == "ALL":
        cur.execute(f"SELECT close, volume FROM {table} WHERE interval='{timeframe}' ORDER BY open_time DESC LIMIT %s", (limit,))
    else:
        cur.execute(f"SELECT close, volume FROM {table} WHERE symbol=%s ORDER BY open_time DESC LIMIT %s", (symbol, limit))
    rows = list(reversed(cur.fetchall()))
    cur.close(); conn.close()
    if len(rows) < 100:
        return {"error": f"Not enough {timeframe} data for {symbol}: {len(rows)} candles"}
    closes = [float(r[0]) for r in rows]
    volumes = [float(r[1]) for r in rows]
    model, scaler, state_map = train(closes, volumes)
    model_file = save_model(model, scaler, state_map, timeframe)
    chars = get_state_characteristics(model, scaler, state_map, timeframe)
    trans = get_transition_matrix(model, state_map, timeframe)
    return {
        "status": "trained",
        "timeframe": timeframe,
        "candles_used": len(rows),
        "symbol": symbol,
        "model_file": model_file,
        "converged": model.monitor_.converged,
        "n_iter": model.monitor_.n_iter,
        "state_characteristics": chars,
        "sample_transitions": {
            "from_strong_bull": dict(zip(
                [r["name"] for r in REGIMES],
                [round(p, 3) for p in trans["matrix"][0]]
            ))
        }
    }


def train_all_timeframes(symbol="BTCUSDT", neon_uri=None):
    """Train HMMs for all three timeframes."""
    results = {}
    for tf, limit in [("1m", 50000), ("1h", 17000), ("4h", 4000)]:
        try:
            r = train_from_db(symbol=symbol, neon_uri=neon_uri, limit=limit, timeframe=tf)
            results[tf] = r
        except Exception as e:
            results[tf] = {"error": str(e)}
    return results


def classify_all_timeframes(symbol, neon_uri=None):
    """Get regime classification across all timeframes for a symbol."""
    import psycopg2
    if neon_uri is None:
        neon_uri = os.environ.get("NEON_URI", "")
    conn = psycopg2.connect(neon_uri)
    cur = conn.cursor()
    results = {}
    for tf, table, limit in [("1m", "candles", 50), ("1h", "candles_1h", 50), ("4h", "candles_4h", 50)]:
        try:
            model, scaler, state_map = load_model(tf)
        except Exception:
            model, scaler, state_map = None, None, None
        cur.execute(f"SELECT close, volume FROM {table} WHERE symbol=%s ORDER BY open_time DESC LIMIT %s", (symbol, limit))
        rows = list(reversed(cur.fetchall()))
        if len(rows) < WINDOW + 1:
            results[tf] = {"regime": 3, "regime_name": "Neutral", "confidence": 0.0, "data_points": len(rows)}
            continue
        closes = [float(r[0]) for r in rows]
        volumes = [float(r[1]) for r in rows]
        regime, conf = classify(closes, volumes, len(rows)-1, model=model, scaler=scaler, state_map=state_map, timeframe=tf)
        results[tf] = {"regime": regime, "regime_name": REGIMES[regime]["name"], "confidence": conf}
    cur.close(); conn.close()
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        symbol = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"
        tf = sys.argv[3] if len(sys.argv) > 3 else "all"
        if tf == "all":
            results = train_all_timeframes(symbol=symbol)
        else:
            results = train_from_db(symbol=symbol, timeframe=tf)
        print(json.dumps(results, indent=2))
    else:
        print("Usage: python -m src.regime train [SYMBOL] [1m|1h|4h|all]")
