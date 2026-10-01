"""Paper trades, random baselines and verdicts.

Every signal becomes a paper trade that enters at the next candle's open. It exits at a
target (2x ATR), a stop (1x ATR) or a time limit, whichever comes first. If the target
and the stop are both touched in the same candle, the stop is assumed to come first.

Each trade is compared with random entries on the same coin, within the same 90 days and
the same market regime (BTC above or below its 200-day average), using identical exits.
A signal only counts as an edge when it beats those random entries after fees, by a margin
that survives correction for every variant ever tried.
"""

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

import config
import indicators as ind

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
REASONS = np.array(["stop", "target", "time"])


def cost_for(symbol):
    return config.COST_MAJORS if symbol in config.MAJORS else config.COST_OTHERS


# --- Regime ---------------------------------------------------------------------

def regime_series(btc_daily, close_times):
    """1 if BTC's last completed daily close was above its 200-day average, 0 if below,
    -1 before there is enough history. Uses only daily candles that had closed by then."""
    ma = ind.sma(btc_daily["close"], config.REGIME_MA_DAYS)
    above = np.where(np.isnan(ma), -1, (btc_daily["close"] > ma).astype(int))
    k = np.searchsorted(btc_daily["close_time"], close_times, side="right") - 1
    return np.where(k >= 0, above[np.maximum(k, 0)], -1)


# --- Exits ----------------------------------------------------------------------

def simulate_exits(c, signal_idx, tf, atr, hold_bars=None):
    """Vectorised exits for trades whose signal fired on the bars in signal_idx.

    Returns a dict of arrays (one entry per trade). Trades without enough future data or
    without an ATR value are marked invalid rather than dropped, so indexes line up."""
    n = len(c["close"])
    T = hold_bars or config.TIME_LIMIT_BARS[tf]
    s = np.asarray(signal_idx, dtype=np.int64)
    e = s + 1
    valid = (e + T - 1 < n) & ~np.isnan(atr[np.minimum(s, n - 1)])
    out = {k: np.full(len(s), np.nan) for k in ("entry_price", "exit_price", "gross")}
    out.update(exit_idx=np.full(len(s), -1, dtype=np.int64),
               reason=np.full(len(s), "", dtype=object), valid=valid)
    if not valid.any():
        return out
    ev, sv = e[valid], s[valid]
    entry = c["open"][ev]
    if hold_bars:
        k = np.full(len(ev), T - 1)
        price = c["close"][ev + T - 1]
        reason = np.full(len(ev), 2)
    else:
        tg = entry + config.TARGET_ATR * atr[sv]
        sp = entry - config.STOP_ATR * atr[sv]
        L = sliding_window_view(c["low"], T)[ev]
        H = sliding_window_view(c["high"], T)[ev]
        O = sliding_window_view(c["open"], T)[ev]
        stop_hit, tg_hit = L <= sp[:, None], H >= tg[:, None]
        first_stop = np.where(stop_hit.any(1), stop_hit.argmax(1), T)
        first_tg = np.where(tg_hit.any(1), tg_hit.argmax(1), T)
        is_stop = (first_stop <= first_tg) & (first_stop < T)
        is_tg = ~is_stop & (first_tg < T)
        k = np.where(is_stop, first_stop, np.where(is_tg, first_tg, T - 1))
        rows = np.arange(len(ev))
        open_k = O[rows, k]
        # a gap through the level fills at the open, not at the level
        price = np.where(is_stop, np.minimum(sp, open_k),
                         np.where(is_tg, np.maximum(tg, open_k), c["close"][ev + T - 1]))
        reason = np.where(is_stop, 0, np.where(is_tg, 1, 2))
    out["entry_price"][valid] = entry
    out["exit_price"][valid] = price
    out["gross"][valid] = price / entry - 1
    out["exit_idx"][valid] = ev + k
    out["reason"][valid] = REASONS[reason]
    return out


def horizon_returns(c, signal_idx, horizons, cost):
    """Net return from the next open to the close h candles later, for each horizon."""
    n = len(c["close"])
    e = np.asarray(signal_idx) + 1
    res = {}
    for h in horizons:
        end = e + h - 1
        ok = end < n
        r = np.full(len(e), np.nan)
        r[ok] = c["close"][end[ok]] / c["open"][e[ok]] - 1 - cost
        res[h] = r
    return res


# --- One variant, all coins -----------------------------------------------------

def run_variant(flags_by_symbol, panel, tf, params, regimes, rng):
    """Turn signal flags into independent paper trades with matched random baselines."""
    hold = params.get("hold_bars")
    horizons = [hold] if hold else config.HORIZON_BARS[tf]
    window_bars = config.RANDOM_WINDOW_DAYS * 24 // config.TF_HOURS[tf]
    M = config.RANDOM_DRAWS_PER_TRADE
    trades = []
    random_nets = []
    random_h = {h: [] for h in horizons}
    for sym, flags in flags_by_symbol.items():
        c = panel[sym]
        idx = np.flatnonzero(flags)
        if len(idx) == 0:
            continue
        atr = ind.atr(c["high"], c["low"], c["close"], config.ATR_WINDOW)
        ex = simulate_exits(c, idx, tf, atr, hold)
        cost = cost_for(sym)
        # keep only trades that start after the previous one on this coin has closed
        keep, busy_until = [], -1
        for j, s in enumerate(idx):
            if ex["valid"][j] and s + 1 > busy_until:
                keep.append(j)
                busy_until = ex["exit_idx"][j]
        if not keep:
            continue
        keep = np.array(keep)
        sig = idx[keep]
        hz = horizon_returns(c, sig, horizons, cost)

        # matched random entries: same coin, +/- window, same regime, same exits and horizons
        reg = regimes[sym]
        n = len(c["close"])
        T = hold or config.TIME_LIMIT_BARS[tf]
        usable = (np.arange(n) + T < n) & ~np.isnan(atr)
        rand_mean = np.full(len(sig), np.nan)
        rand_h = {h: np.full(len(sig), np.nan) for h in horizons}
        for r_val in np.unique(reg[sig]):
            pool = np.flatnonzero(usable & (reg == r_val))
            mine = np.flatnonzero(reg[sig] == r_val)
            if len(pool) == 0:
                continue
            lo = np.searchsorted(pool, sig[mine] - window_bars)
            hi = np.searchsorted(pool, sig[mine] + window_bars, side="right")
            has = hi > lo
            if not has.any():
                continue
            draws = pool[rng.integers(lo[has][:, None], hi[has][:, None],
                                      size=(has.sum(), M))]
            rx = simulate_exits(c, draws.ravel(), tf, atr, hold)
            rnet = (rx["gross"] - cost).reshape(-1, M)
            rand_mean[mine[has]] = np.nanmean(rnet, axis=1)
            random_nets.append(rnet[~np.isnan(rnet)])
            for h, v in horizon_returns(c, draws.ravel(), horizons, cost).items():
                v = v.reshape(-1, M)
                rand_h[h][mine[has]] = _row_mean(v)
                random_h[h].append(v[~np.isnan(v)])

        for jj, j in enumerate(keep):
            s = idx[j]
            gross = ex["gross"][j]
            net = gross - cost
            trades.append({
                "symbol": sym, "bar_time": int(c["t"][s]), "detected_at": int(c["close_time"][s]),
                "regime": int(reg[s]), "entry_time": int(c["t"][s + 1]),
                "entry_price": float(ex["entry_price"][j]),
                "exit_time": int(c["close_time"][ex["exit_idx"][j]]),
                "exit_price": float(ex["exit_price"][j]), "exit_reason": ex["reason"][j],
                "bars_held": int(ex["exit_idx"][j] - s), "gross": float(gross), "net": float(net),
                "random_mean": None if np.isnan(rand_mean[jj]) else float(rand_mean[jj]),
                "excess": None if np.isnan(rand_mean[jj]) else float(net - rand_mean[jj]),
                "horizons": {str(h): {"net": _f(v[jj]), "random": _f(rand_h[h][jj])}
                             for h, v in hz.items()},
            })
    pooled = {
        "exit": np.concatenate(random_nets) if random_nets else np.array([]),
        "horizons": {str(h): (np.concatenate(v) if v else np.array([])) for h, v in random_h.items()},
    }
    return trades, pooled


def _f(x):
    return None if np.isnan(x) else float(x)


def _row_mean(v):
    """Mean of each row, ignoring NaN; NaN for rows with no values (no warning)."""
    ok = ~np.isnan(v)
    cnt = ok.sum(axis=1)
    tot = np.where(ok, v, 0.0).sum(axis=1)
    return np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)


# --- Statistics -----------------------------------------------------------------

def _norm_sf(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def cluster_t(x, clusters):
    """t-statistic of the mean of x with standard errors clustered by calendar week, so
    ten coins breaking out on the same day count as one piece of evidence, not ten."""
    n = len(x)
    ids = np.unique(clusters)
    G = len(ids)
    if n < 2 or G < 2:
        return float("nan")
    m = x.mean()
    sums = np.array([np.sum(x[clusters == g] - m) for g in ids])
    var = G / (G - 1) * np.sum(sums ** 2) / n ** 2
    return float(m / math.sqrt(var)) if var > 0 else float("nan")


def cluster_bootstrap_ci(x, clusters, rng, resamples):
    ids = np.unique(clusters)
    if len(ids) < 2:
        return [None, None]
    groups = [x[clusters == g] for g in ids]
    means = []
    for _ in range(resamples):
        pick = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in pick]).mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [float(lo), float(hi)]


def tier(n):
    for limit, label in config.VERDICT_TIERS:
        if n < limit:
            return label
    return config.VERDICT_TOP


def score(variant, family, tf, trades, pooled, rng):
    """pooled: the random entries' results from run_variant ({"exit": ..., "horizons": {...}})."""
    random_nets = pooled["exit"]
    nets = np.array([t["net"] for t in trades])
    paired = [t for t in trades if t["excess"] is not None]
    ex = np.array([t["excess"] for t in paired])
    weeks = np.array([t["entry_time"] // WEEK_MS for t in paired])
    n = len(nets)
    s = {"variant": variant, "family": family, "tf": tf, "n": n}
    if n == 0:
        s.update(hit=None, random_hit=None, mean=None, median=None, random_mean=None,
                 excess=None, t=None, t_cluster=None, p=None, profit_factor=None,
                 details={"tier": "No verdict"})
        return s
    wins, losses = nets[nets > 0].sum(), -nets[nets < 0].sum()
    t_plain = (float(ex.mean() / (ex.std(ddof=1) / math.sqrt(len(ex))))
               if len(ex) > 1 and ex.std(ddof=1) > 0 else float("nan"))
    t_cl = cluster_t(ex, weeks) if len(ex) > 1 else float("nan")
    reasons = {r: sum(1 for t in trades if t["exit_reason"] == r) for r in ("target", "stop", "time")}
    horizons = {}
    for h in trades[0]["horizons"]:
        both = [t for t in trades if t["horizons"][h]["net"] is not None
                and t["horizons"][h]["random"] is not None]
        if not both:
            continue
        v = np.array([t["horizons"][h]["net"] for t in both])
        hx = v - np.array([t["horizons"][h]["random"] for t in both])
        rp = pooled["horizons"].get(h, np.array([]))
        horizons[h] = {
            "n": len(v), "hit": float((v > 0).mean()), "mean": float(v.mean()),
            "random_hit": float((rp > 0).mean()) if len(rp) else None,
            "random_mean": float(rp.mean()) if len(rp) else None,
            "excess": float(hx.mean()),
            "t_cluster": cluster_t(hx, np.array([t["entry_time"] // WEEK_MS for t in both])),
        }
    by_regime = {}
    for r, label in ((1, "btc_above_200d"), (0, "btc_below_200d")):
        v = np.array([t["excess"] for t in paired if t["regime"] == r])
        if len(v):
            by_regime[label] = {"n": len(v), "mean_excess": float(v.mean())}
    s.update(
        hit=float((nets > 0).mean()),
        random_hit=float((random_nets > 0).mean()) if len(random_nets) else None,
        mean=float(nets.mean()), median=float(np.median(nets)),
        random_mean=float(random_nets.mean()) if len(random_nets) else None,
        excess=float(ex.mean()) if len(ex) else None,
        t=t_plain, t_cluster=t_cl,
        p=_norm_sf(t_cl) if not math.isnan(t_cl) else None,
        profit_factor=float(wins / losses) if losses > 0 else None,
        details={
            "tier": tier(n), "exits": reasons,
            "avg_bars_held": float(np.mean([t["bars_held"] for t in trades])),
            "excess_ci95": cluster_bootstrap_ci(ex, weeks, rng, config.BOOTSTRAP_RESAMPLES)
            if len(ex) > 1 else [None, None],
            "horizons": horizons, "by_regime": by_regime, "weeks": int(len(np.unique(weeks))),
        },
    )
    return s


def correct_and_judge(scores, trials):
    """Holm and Benjamini-Hochberg across every variant ever tried, then a verdict each.
    Variants tried in earlier runs but not scored now count as trials with p = 1."""
    ps = [(s["p"] if s.get("p") is not None else 1.0) for s in scores]
    m = max(trials, len(ps))
    order = np.argsort(ps)
    holm = [1.0] * len(ps)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        holm[i] = running
    bh = [1.0] * len(ps)
    running = 1.0
    for rank in range(len(order) - 1, -1, -1):
        i = order[rank]
        running = min(running, ps[i] * m / (rank + 1))
        bh[i] = min(1.0, running)
    for s, ph, q in zip(scores, holm, bh):
        s["p_holm"], s["q_bh"] = ph, q
        n, tc = s["n"], s.get("t_cluster")
        if s["variant"] in config.FORWARD_ONLY_VARIANTS:
            s["verdict"] = config.FORWARD_ONLY_VERDICT
        elif n < config.VERDICT_TIERS[0][0] or tc is None or math.isnan(tc):
            s["verdict"] = "No verdict"
        elif tc >= config.EDGE_T and ph < config.ALPHA:
            s["verdict"] = "Edge"
        elif tc <= config.LOSING_T:
            s["verdict"] = "Losing"
        else:
            s["verdict"] = "No edge"
    return scores
