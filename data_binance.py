"""Downloads from Binance's public API. No account or key needed.

Only closed candles are stored: the candle that is still forming is dropped, so
nothing downstream can ever see a price that later changes.
"""

import datetime as dt
import time

import requests

import config
import store

_session = requests.Session()


def _get(base, path, params, attempts=6):
    """GET with backoff on rate limits (429/418) and server errors."""
    for i in range(attempts):
        try:
            r = _session.get(base + path, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** i)
            continue
        if r.status_code in (429, 418):
            time.sleep(int(r.headers.get("Retry-After", 60)))
            continue
        if r.status_code >= 500:
            time.sleep(2 ** i)
            continue
        used = int(r.headers.get("X-MBX-USED-WEIGHT-1M", 0) or 0)
        if used > config.MAX_USED_WEIGHT:
            time.sleep(30)
        time.sleep(config.REQUEST_PAUSE_S)
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Binance kept failing for {path} {params}")


def to_ms(date_str):
    d = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


def now_ms():
    return int(time.time() * 1000)


# --- Universe -------------------------------------------------------------------

def pick_universe(conn):
    """Top USDT pairs by average daily quote volume over the last 30 days, minus stablecoins,
    wrapped assets, leveraged tokens and coins with less than 180 days of spot history.

    Today's 24h volume only shortlists candidates: ranking on one day picked coins that were
    spiking that day and dropped them again the next."""
    info = _get(config.BINANCE_SPOT, "/api/v3/exchangeInfo", {"permissions": "SPOT"})
    bases = {s["symbol"]: s["baseAsset"] for s in info["symbols"]
             if s["status"] == "TRADING" and s["quoteAsset"] == config.QUOTE}
    all_bases = set(bases.values())

    def leveraged(base):
        return any(base.endswith(sfx) and base[: -len(sfx)] in all_bases
                   for sfx in config.LEVERAGED_SUFFIXES)

    tickers = _get(config.BINANCE_SPOT, "/api/v3/ticker/24hr", {"type": "MINI"})
    shortlist = sorted(
        ((t["symbol"], float(t["quoteVolume"])) for t in tickers
         if t["symbol"] in bases
         and bases[t["symbol"]] not in config.EXCLUDED_BASES
         and not leveraged(bases[t["symbol"]])),
        key=lambda x: x[1], reverse=True,
    )[: config.UNIVERSE_PREFILTER]

    cutoff = now_ms()
    min_age_ms = config.UNIVERSE_MIN_HISTORY_DAYS * 86_400_000
    averaged = []
    for sym, _ in shortlist:
        first = _get(config.BINANCE_SPOT, "/api/v3/klines",
                     {"symbol": sym, "interval": "1d", "startTime": 0, "limit": 1})
        if not first or cutoff - int(first[0][0]) < min_age_ms:
            continue
        recent = _get(config.BINANCE_SPOT, "/api/v3/klines",
                      {"symbol": sym, "interval": "1d", "limit": config.UNIVERSE_VOLUME_DAYS + 1})
        done = [r for r in recent if int(r[6]) < cutoff][-config.UNIVERSE_VOLUME_DAYS:]
        lo, hi = config.STABLECOIN_BAND
        if done and all(lo <= float(r[4]) <= hi for r in done):
            continue        # a stablecoin by behaviour, whatever it is called
        closed = [float(r[7]) for r in done]
        if closed:
            averaged.append((sym, sum(closed) / len(closed)))
    ranked = sorted(averaged, key=lambda x: x[1], reverse=True)[: config.UNIVERSE_SIZE]
    store.save_universe(conn, dt.date.today().isoformat(), ranked)
    return [s for s, _ in ranked]


# --- Candles --------------------------------------------------------------------

def download_klines(conn, symbol, tf, since_ms):
    last = store.last_open_time(conn, symbol, tf)
    start = since_ms if last is None else last + 1
    added = 0
    while True:
        rows = _get(config.BINANCE_SPOT, "/api/v3/klines",
                    {"symbol": symbol, "interval": tf, "startTime": start, "limit": 1000})
        if not rows:
            break
        cutoff = now_ms()
        closed = [r for r in rows if int(r[6]) < cutoff]
        store.insert_candles(conn, symbol, tf, closed)
        added += len(closed)
        if len(rows) < 1000 or len(closed) < len(rows):
            break
        start = int(rows[-1][0]) + 1
    return added


def download_funding(conn, symbol, since_ms):
    """Perpetual futures funding history. Coins without a perpetual are skipped quietly."""
    last = store.last_funding_time(conn, symbol)
    start = since_ms if last is None else last + 1
    added = 0
    while True:
        try:
            rows = _get(config.BINANCE_FUTURES, "/fapi/v1/fundingRate",
                        {"symbol": symbol, "startTime": start, "limit": 1000})
        except requests.HTTPError:
            return added
        if not rows:
            break
        store.insert_funding(conn, symbol, rows)
        added += len(rows)
        if len(rows) < 1000:
            break
        start = int(rows[-1]["fundingTime"]) + 1
    return added


def download_all(conn, symbols, timeframes, since):
    since_ms = to_ms(since)
    for i, sym in enumerate(symbols, 1):
        parts = []
        for tf in timeframes:
            parts.append(f"{tf} +{download_klines(conn, sym, tf, since_ms)}")
        try:
            parts.append(f"funding +{download_funding(conn, sym, since_ms)}")
        except RuntimeError as e:
            parts.append(f"funding skipped ({e})")
        print(f"  [{i:2}/{len(symbols)}] {sym:<12} " + "  ".join(parts), flush=True)
