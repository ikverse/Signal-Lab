"""The four main signals: trend state, Donchian breakout, time-series momentum and
cross-sectional momentum.

A signal on bar i means "detected when bar i closed". Each function only looks at
bars up to i, so running it on history cut off at bar i gives the same answer for
bar i as running it on the full history. backtest.py checks exactly that.
"""

import math

import numpy as np

import config
import indicators as ind

DAY_MS = 86_400_000


def bars_per_week(tf):
    return 7 * 24 // config.TF_HOURS[tf]


def is_utc_midnight(t):
    return t % DAY_MS == 0


def is_monday_midnight(t):
    # 1 Jan 1970 was a Thursday, so (days + 3) % 7 == 0 on Mondays.
    return is_utc_midnight(t) & (((t // DAY_MS) + 3) % 7 == 0)


def params(**kw):
    """Signal settings as a sorted tuple, so (name, family, params) can be a dict key."""
    return tuple(sorted(kw.items()))


def first_bar_of(state):
    """True only on the first bar of each run of True values."""
    prev = np.concatenate([[False], state[:-1]])
    return state & ~prev


def trend_state(c, tf):
    out = {}
    for n in config.TREND_MA_WINDOWS:
        out[(f"trend_ma{n}_{tf}", "trend_state", params(ma=n))] = ind.crossed_above(
            c["close"], ind.sma(c["close"], n))
    return out


def donchian(c, tf):
    out = {}
    for n in config.DONCHIAN_LOOKBACKS:
        above = c["close"] > ind.rolling_max_prior(c["high"], n)
        out[(f"donchian{n}_{tf}", "donchian", params(lookback=n))] = first_bar_of(above)
    return out


def rolling_quantile_daily(values, t, history_days, q, tf):
    """Quantile of `values` over the trailing window, recomputed at each UTC midnight bar
    and held until the next one. Recompute points depend on timestamps, not on how much
    history was loaded, so the result for a bar never changes when more data arrives."""
    thr = np.full(len(values), np.nan)
    window_ms = history_days * DAY_MS
    # need at least half a window of history before trusting the quantile
    min_count = history_days * 24 // config.TF_HOURS[tf] // 2
    for j in np.flatnonzero(is_utc_midnight(t)):
        lo = np.searchsorted(t, t[j] - window_ms, side="right")
        w = values[lo:j + 1]
        w = w[~np.isnan(w)]
        if len(w) >= min_count:
            thr[j] = np.quantile(w, q)
    # hold each value until the next midnight
    idx = np.where(is_utc_midnight(t), np.arange(len(t)), -1)
    idx = np.maximum.accumulate(idx)
    held = np.where(idx >= 0, thr[np.maximum(idx, 0)], np.nan)
    return held


def ts_momentum(c, tf):
    out = {}
    for w in config.TS_MOMENTUM_WEEKS:
        ret = ind.pct_return(c["close"], w * bars_per_week(tf))
        thr = rolling_quantile_daily(ret, c["t"], config.TS_MOMENTUM_HISTORY_DAYS,
                                     config.TS_MOMENTUM_TOP_QUANTILE, tf)
        strong = ret >= thr          # NaN compares False
        out[(f"tsmom{w}w_{tf}", "ts_momentum", params(weeks=w))] = first_bar_of(strong)
    return out


def xs_momentum(panel, tf):
    """panel: {symbol: candles}. Every Monday 00:00 UTC bar, the coins in the top fifth by
    w-week return get a signal. Returns {variant_key: {symbol: bool array}}."""
    out = {}
    for w in config.XS_MOMENTUM_WEEKS:
        lag = w * bars_per_week(tf)
        rets = {s: ind.pct_return(c["close"], lag) for s, c in panel.items()}
        flags = {s: np.zeros(len(c["t"]), dtype=bool) for s, c in panel.items()}
        mondays = sorted(set().union(*(set(c["t"][is_monday_midnight(c["t"])].tolist())
                                       for c in panel.values())))
        for T in mondays:
            ranked = []
            for s, c in panel.items():
                i = np.searchsorted(c["t"], T)
                if i < len(c["t"]) and c["t"][i] == T and not np.isnan(rets[s][i]):
                    ranked.append((rets[s][i], s, i))
            if len(ranked) < config.XS_MOMENTUM_MIN_COINS:
                continue
            ranked.sort(reverse=True)
            k = math.ceil(config.XS_MOMENTUM_TOP_FRACTION * len(ranked))
            for _, s, i in ranked[:k]:
                flags[s][i] = True
        out[(f"xsmom{w}w_{tf}", "xs_momentum", params(weeks=w))] = flags
    return out


def single_coin_signals(c, tf):
    """All per-coin main signals for one coin and timeframe."""
    out = {}
    for fn in (trend_state, donchian, ts_momentum):
        out.update(fn(c, tf))
    return out
