"""Indicators, each a single pass over numpy arrays.

Every function returns an array the same length as its input, with NaN where there
is not yet enough history. Value i only ever uses data up to and including bar i.
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def _pad(values, n_missing):
    return np.concatenate([np.full(n_missing, np.nan), values])


def sma(x, n):
    """Simple moving average of the last n values, including the current one."""
    if len(x) < n:
        return np.full(len(x), np.nan)
    c = np.cumsum(np.insert(x.astype(float), 0, 0.0))
    return _pad((c[n:] - c[:-n]) / n, n - 1)


def rolling_max_prior(x, n):
    """Highest value of the n bars before bar i (bar i itself excluded)."""
    if len(x) <= n:
        return np.full(len(x), np.nan)
    return _pad(sliding_window_view(x, n).max(axis=1)[:-1], n)


def rolling_std(x, n):
    """Standard deviation of the last n values, including the current one."""
    if len(x) < n:
        return np.full(len(x), np.nan)
    return _pad(sliding_window_view(x, n).std(axis=1), n - 1)


def true_range(high, low, close):
    prev = np.concatenate([[close[0]], close[:-1]])
    return np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])


def atr(high, low, close, n):
    """Average true range: simple mean of the last n true ranges."""
    return sma(true_range(high, low, close), n)


def pct_return(close, lag):
    """Return over the last `lag` bars: close[i] / close[i - lag] - 1."""
    out = np.full(len(close), np.nan)
    if len(close) > lag:
        out[lag:] = close[lag:] / close[:-lag] - 1
    return out


def rsi(close, n=14):
    """Wilder's RSI, seeded with the simple average of the first n changes."""
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    ch = np.diff(close)
    up, dn = np.maximum(ch, 0), np.maximum(-ch, 0)
    g, l = up[:n].mean(), dn[:n].mean()
    out[n] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(n, len(ch)):
        g = (g * (n - 1) + up[i]) / n
        l = (l * (n - 1) + dn[i]) / n
        out[i + 1] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def crossed_above(a, b):
    """True on the bar where a moves from <= b to > b."""
    out = np.zeros(len(a), dtype=bool)
    out[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return out
