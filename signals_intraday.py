"""Two intraday experiments, run on 1h candles only.

Big-move fade: after an unusually large drop over 1, 2 or 4 hours, buy and expect part
of it to bounce back. Studies found small reversals in BTC after big jumps (2015-2018 data).

Intraday momentum: when the first hour of the UTC day is unusually strong, buy the last
hour of the same day. A 2022 study found the start of the day predicts its end, before fees.
"""

import numpy as np

import config
import indicators as ind
from signals_trend import DAY_MS, first_bar_of, is_utc_midnight, params

HOUR_MS = 3_600_000


def big_move_fade(c, tf="1h"):
    out = {}
    vol_bars = config.FADE_VOL_DAYS * 24
    for k in config.FADE_HOURS:
        r = ind.pct_return(c["close"], k)
        sd = ind.rolling_std(r, vol_bars)
        sd_before = np.concatenate([[np.nan], sd[:-1]])   # the move itself must not inflate its yardstick
        big_drop = r < -config.FADE_SIGMA * sd_before
        out[(f"fade{k}h_{tf}", "big_move_fade", params(hours=k, sigma=config.FADE_SIGMA))] = \
            first_bar_of(big_drop)
        if k == 1:
            # Declared on 2026-10-01 after the first backtest hinted at a 24-hour bounce: same entry,
            # held 24 candles with no target or stop. Judged on live paper trades only.
            out[(f"fade1h_hold24_{tf}", "big_move_fade",
                 params(hours=1, sigma=config.FADE_SIGMA, hold_bars=24))] = first_bar_of(big_drop)
    return out


def intraday_momentum(c, tf="1h"):
    """Signal on the 22:00 bar (detected when it closes at 23:00), so the paper trade enters
    at the 23:00 open and is held for that one final hour of the UTC day."""
    t = c["t"]
    flags = np.zeros(len(t), dtype=bool)
    mid = np.flatnonzero(is_utc_midnight(t))
    first_hour = c["close"][mid] / c["open"][mid] - 1
    mid_days = t[mid] // DAY_MS
    min_count = config.INTRADAY_MOM_HISTORY_DAYS // 2
    for i in np.flatnonzero(t % DAY_MS == 22 * HOUR_MS):
        day = t[i] // DAY_MS
        k = np.searchsorted(mid_days, day)
        if k >= len(mid_days) or mid_days[k] != day:
            continue
        past = first_hour[(mid_days >= day - config.INTRADAY_MOM_HISTORY_DAYS) & (mid_days < day)]
        if len(past) < min_count:
            continue
        thr = np.quantile(past, config.INTRADAY_MOM_TOP_QUANTILE)
        flags[i] = first_hour[k] > 0 and first_hour[k] >= thr
    key = ("intraday_mom_1h", "intraday_momentum",
           params(top_quantile=config.INTRADAY_MOM_TOP_QUANTILE, hold_bars=1))
    return {key: flags}


def intraday_signals(c, tf):
    if tf != "1h":
        return {}
    out = big_move_fade(c, tf)
    out.update(intraday_momentum(c, tf))
    return out
