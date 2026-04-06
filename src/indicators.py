"""
Technical Indicators Library
=============================
Pure-Python implementations. No numpy/pandas dependency.
All functions take lists of floats and return lists of floats.
"""
import math


def sma(values, period):
    """Simple Moving Average."""
    out = [0.0] * len(values)
    if len(values) < period:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, len(values)):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def ema(values, period):
    """Exponential Moving Average."""
    out = [0.0] * len(values)
    if len(values) < period:
        return out
    m = 2.0 / (period + 1)
    out[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        out[i] = (values[i] - out[i - 1]) * m + out[i - 1]
    return out


def rsi(closes, period=14):
    """Relative Strength Index."""
    out = [50.0] * len(closes)
    if len(closes) < period + 1:
        return out
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def bollinger_bands(closes, period=20, num_std=2.0):
    """Bollinger Bands. Returns (upper, middle, lower, bandwidth)."""
    n = len(closes)
    upper = [0.0] * n
    middle = [0.0] * n
    lower = [0.0] * n
    bandwidth = [0.0] * n
    mid = sma(closes, period)
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        avg = mid[i]
        var = sum((x - avg) ** 2 for x in window) / period
        std = math.sqrt(var)
        upper[i] = avg + num_std * std
        middle[i] = avg
        lower[i] = avg - num_std * std
        bandwidth[i] = (upper[i] - lower[i]) / avg * 100 if avg > 0 else 0
    return upper, middle, lower, bandwidth


def atr(highs, lows, closes, period=14):
    """Average True Range (Wilder's smoothing)."""
    n = len(closes)
    out = [0.0] * n
    if n < 2:
        return out
    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if n < period:
        return out
    out[period - 1] = sum(trs[:period]) / period
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def donchian_channel(highs, lows, period=20):
    """Donchian Channel. Returns (upper, lower, mid)."""
    n = len(highs)
    upper = [0.0] * n
    lower = [0.0] * n
    mid = [0.0] * n
    for i in range(period, n):
        upper[i] = max(highs[i - period:i])
        lower[i] = min(lows[i - period:i])
        mid[i] = (upper[i] + lower[i]) / 2
    return upper, lower, mid


def macd(closes, fast=12, slow=26, signal=9):
    """MACD. Returns (macd_line, signal_line, histogram)."""
    ef = ema(closes, fast)
    es = ema(closes, slow)
    n = len(closes)
    macd_line = [0.0] * n
    for i in range(slow - 1, n):
        macd_line[i] = ef[i] - es[i]
    sig = ema(macd_line, signal)
    hist = [0.0] * n
    for i in range(n):
        hist[i] = macd_line[i] - sig[i]
    return macd_line, sig, hist


def adx(highs, lows, closes, period=14):
    """Average Directional Index. Returns (adx, plus_di, minus_di)."""
    n = len(closes)
    adx_out = [0.0] * n
    pdi = [0.0] * n
    mdi = [0.0] * n
    if n < period + 1:
        return adx_out, pdi, mdi

    tr_list = []
    pdm_list = []
    mdm_list = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm = up if up > down and up > 0 else 0
        mdm = down if down > up and down > 0 else 0
        tr_list.append(tr)
        pdm_list.append(pdm)
        mdm_list.append(mdm)

    # Initial smoothed values
    atr_s = sum(tr_list[:period]) / period
    pdm_s = sum(pdm_list[:period]) / period
    mdm_s = sum(mdm_list[:period]) / period

    dx_list = []
    for i in range(period - 1, len(tr_list)):
        if i == period - 1:
            pass
        else:
            atr_s = (atr_s * (period - 1) + tr_list[i]) / period
            pdm_s = (pdm_s * (period - 1) + pdm_list[i]) / period
            mdm_s = (mdm_s * (period - 1) + mdm_list[i]) / period
        if atr_s > 0:
            pdi[i + 1] = pdm_s / atr_s * 100
            mdi[i + 1] = mdm_s / atr_s * 100
        denom = pdi[i + 1] + mdi[i + 1]
        dx = abs(pdi[i + 1] - mdi[i + 1]) / denom * 100 if denom > 0 else 0
        dx_list.append(dx)

    if len(dx_list) >= period:
        adx_val = sum(dx_list[:period]) / period
        adx_out[2 * period] = adx_val
        for j in range(period, len(dx_list)):
            adx_val = (adx_val * (period - 1) + dx_list[j]) / period
            idx = j + period + 1
            if idx < n:
                adx_out[idx] = adx_val

    return adx_out, pdi, mdi


def rate_of_change(closes, period=14):
    """Rate of Change (momentum)."""
    out = [0.0] * len(closes)
    for i in range(period, len(closes)):
        if closes[i - period] > 0:
            out[i] = (closes[i] - closes[i - period]) / closes[i - period]
    return out


def vwap_ratio(closes, volumes, period=20):
    """VWAP ratio: price / VWAP. >1 = above VWAP, <1 = below."""
    n = len(closes)
    out = [1.0] * n
    for i in range(period, n):
        cv = sum(closes[j] * volumes[j] for j in range(i - period, i))
        v = sum(volumes[i - period:i])
        if v > 0:
            vwap = cv / v
            out[i] = closes[i] / vwap if vwap > 0 else 1.0
    return out


def squeeze(bandwidth, lookback=120):
    """Bollinger squeeze detection: bandwidth at N-bar low."""
    n = len(bandwidth)
    out = [False] * n
    for i in range(lookback, n):
        if bandwidth[i] > 0 and bandwidth[i] <= min(
            b for b in bandwidth[i - lookback:i] if b > 0
        ):
            out[i] = True
    return out
