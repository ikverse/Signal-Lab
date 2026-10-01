"""The live engine: the same signals and exits as the backtest, run as candles close.

Every 30 seconds it checks whether a 1h, 4h or daily candle has closed. If one has, it fetches
the new candles, runs every signal, opens a paper trade for each new one (entry at the next
candle's open, exactly as in the backtest) and closes open trades that reached their target,
stop or time limit. Between candles it watches prices for sudden moves.

The signal code is the backtest's own, called on recent history; the repaint check is what
guarantees the last-candle answer here matches what the backtest would have said.
"""

import collections
import threading
import time
import traceback

import numpy as np

import alerts
import config
import data_binance
import indicators as ind
import scorecard
import store
from backtest import compute_signals

TF_MS = {tf: h * 3_600_000 for tf, h in config.TF_HOURS.items()}
SETTLE_MS = 20_000          # give Binance a moment after the close before asking for the candle
DAY_MS = 86_400_000

FAMILY_WORDS = {
    "donchian": "broke above its {n}-candle high",
    "trend_state": "crossed above its {n}-candle average",
    "ts_momentum": "has an unusually strong {n}-week run",
    "xs_momentum": "is among the strongest coins over {n} weeks",
    "big_move_fade": "dropped sharply in {n}h; watching for a bounce",
    "intraday_momentum": "had an unusually strong first hour",
}
TF_WORDS = {"1h": "hourly", "4h": "4-hour", "1d": "daily"}


def short(symbol):
    return symbol[:-len(config.QUOTE)] if symbol.endswith(config.QUOTE) else symbol


def describe(family, params, symbol, tf):
    n = next((params[k] for k in ("lookback", "ma", "weeks", "hours") if k in params), "")
    words = FAMILY_WORDS.get(family, "signalled").format(n=n)
    return f"{short(symbol)} {words}", f"{short(symbol)} {words.split(';')[0]} on the {TF_WORDS[tf]} chart"


def last_closed_open(now_ms, tf):
    """Open time of the newest candle that has closed by now_ms."""
    return (now_ms // TF_MS[tf]) * TF_MS[tf] - TF_MS[tf]


def check_exit(c, entry_idx, T, target, stop):
    """Same rules as scorecard.simulate_exits, for a trade that may still be running.
    Returns (exit_idx, price, reason) or None while it is still open."""
    n = len(c["close"])
    for k in range(min(T, n - entry_idx)):
        i = entry_idx + k
        if stop is not None and c["low"][i] <= stop:
            return i, min(stop, c["open"][i]), "stop"
        if target is not None and c["high"][i] >= target:
            return i, max(target, c["open"][i]), "target"
    if n - entry_idx >= T:
        i = entry_idx + T - 1
        return i, c["close"][i], "time"
    return None


class Engine:
    def __init__(self, fetch=data_binance, notify=alerts.notify, clock=time.time, db_path=None):
        self.fetch = fetch
        self.notify = notify
        self.clock = clock
        self.db_path = db_path
        self.rng = np.random.default_rng(config.RANDOM_SEED)
        self.prices = {}                                   # symbol -> latest price
        self.history = collections.defaultdict(collections.deque)
        self.last_processed = {}
        self.status = {"started_at": int(clock() * 1000), "last_tick": None, "last_error": None,
                       "price_watch_at": None, "update_checked_at": None, "processed": {}}
        self._stop = threading.Event()
        self._last_price_watch = 0.0
        self._last_update_check = 0.0

    # --- setup ---------------------------------------------------------------------

    def connect(self):
        return store.connect(self.db_path)

    def universe(self, conn):
        return store.latest_universe(conn) or ["BTCUSDT", "ETHUSDT"]

    def init_state(self, conn):
        """Start from the newest candle already stored, so history is never re-alerted."""
        for tf in config.TIMEFRAMES:
            row = conn.execute("SELECT MAX(open_time) FROM candles WHERE tf=?", (tf,)).fetchone()
            self.last_processed[tf] = row[0] if row and row[0] else last_closed_open(self.now_ms(), tf)

    def now_ms(self):
        return int(self.clock() * 1000)

    # --- the loop ------------------------------------------------------------------

    def run_forever(self):
        conn = self.connect()
        self.init_state(conn)
        while not self._stop.is_set():
            self.tick(conn)
            self._stop.wait(config.LIVE_TICK_S)

    def stop(self):
        self._stop.set()

    def tick(self, conn):
        self.status["last_tick"] = self.now_ms()
        settings = store.get_settings(conn)
        for tf in config.TIMEFRAMES:
            due = last_closed_open(self.now_ms() - SETTLE_MS, tf)
            if due > self.last_processed.get(tf, 0):
                self._guard(f"{tf} candle", lambda: self.process_tf(conn, tf, settings))
        if self.clock() - self._last_price_watch >= config.PRICE_WATCH_EVERY_S:
            self._last_price_watch = self.clock()
            self._guard("price watch", lambda: self.price_watch(conn, settings))
        if (settings.get("check_updates", True)
                and self.clock() - self._last_update_check >= config.UPDATE_CHECK_HOURS * 3600):
            self._last_update_check = self.clock()
            self._guard("update check", lambda: self.update_check(conn, settings))

    def _guard(self, what, fn):
        try:
            fn()
        except Exception as e:          # one failed step must never stop the engine
            self.status["last_error"] = {"at": self.now_ms(), "step": what, "error": repr(e),
                                         "trace": traceback.format_exc(limit=4)}
            print(f"[engine] {what} failed: {e!r}", flush=True)

    # --- candles, signals, trades --------------------------------------------------

    def process_tf(self, conn, tf, settings):
        symbols = self.universe(conn)
        since = self.now_ms() - config.LIVE_HISTORY_DAYS * DAY_MS
        for sym in symbols:
            self.fetch.download_klines(conn, sym, tf, since)
        if tf != "1d":
            self.fetch.download_klines(conn, "BTCUSDT", "1d", since)
        btc_daily = store.load_candles(conn, "BTCUSDT", "1d", 0)
        panel = {}
        for sym in symbols:
            c = store.load_candles(conn, sym, tf, since)
            if c is not None and len(c["t"]) > 200:
                panel[sym] = c
        if not panel or btc_daily is None:
            return
        newest = max(int(c["t"][-1]) for c in panel.values())
        regimes = {s: scorecard.regime_series(btc_daily, c["close_time"]) for s, c in panel.items()}
        previous = self.last_processed.get(tf, newest)
        opened = []
        for (variant, family, frozen), flags in sorted(compute_signals(panel, tf).items()):
            params = dict(frozen)
            for sym, f in flags.items():
                c = panel[sym]
                for s in np.flatnonzero(f & (c["t"] > previous)):
                    tid = self.open_trade(conn, variant, family, params, sym, tf, c, int(s), regimes[sym])
                    if tid and int(c["t"][s]) == newest:
                        opened.append((variant, family, params, sym))
        self.manage_open(conn, tf, panel, regimes)
        self.last_processed[tf] = newest
        self.status["processed"][tf] = newest
        self.alert_signals(conn, tf, opened, settings)

    def open_trade(self, conn, variant, family, params, sym, tf, c, s, regime):
        if store.has_open_trade(conn, variant, sym):
            return None              # same rule as the backtest: one trade per coin and variant at a time
        atr = ind.atr(c["high"], c["low"], c["close"], config.ATR_WINDOW)[s]
        if np.isnan(atr):
            return None
        entry_time = int(c["t"][s]) + TF_MS[tf]
        if s + 1 < len(c["t"]):
            entry = float(c["open"][s + 1])
        else:
            entry = self.forming_open(sym, tf, entry_time)
            if entry is None:
                return None
        hold = params.get("hold_bars")
        T = hold or config.TIME_LIMIT_BARS[tf]
        return store.open_live_trade(conn, {
            "variant": variant, "family": family, "symbol": sym, "tf": tf,
            "bar_time": int(c["t"][s]), "detected_at": int(c["close_time"][s]), "regime": int(regime[s]),
            "entry_time": entry_time, "entry_price": entry,
            "target": None if hold else entry + config.TARGET_ATR * atr,
            "stop": None if hold else entry - config.STOP_ATR * atr,
            "hold_bars": T, "exit_due": entry_time + T * TF_MS[tf] - 1,
        })

    def forming_open(self, sym, tf, open_time):
        """The open of the candle that has just started: final the moment it starts."""
        rows = self.fetch._get(config.BINANCE_SPOT, "/api/v3/klines",
                               {"symbol": sym, "interval": tf, "startTime": open_time, "limit": 1})
        if rows and int(rows[0][0]) == open_time:
            return float(rows[0][1])
        return None

    def manage_open(self, conn, tf, panel, regimes):
        for t in store.live_trades(conn, status="open"):
            if t["tf"] != tf or t["symbol"] not in panel:
                continue
            c = panel[t["symbol"]]
            e = int(np.searchsorted(c["t"], t["entry_time"]))
            if e >= len(c["t"]) or c["t"][e] != t["entry_time"]:
                continue
            res = check_exit(c, e, t["hold_bars"], t["target"], t["stop"])
            if res is None:
                continue
            i, price, reason = res
            cost = scorecard.cost_for(t["symbol"])
            gross = price / t["entry_price"] - 1
            net = gross - cost
            rnd = self.random_mean(c, e - 1, tf, t, regimes[t["symbol"]], cost)
            store.close_live_trade(conn, t["id"], {
                "exit_time": int(c["close_time"][i]), "exit_price": float(price), "exit_reason": reason,
                "bars_held": int(i - e + 1), "gross": float(gross), "net": float(net),
                "random_mean": rnd, "excess": None if rnd is None else float(net - rnd),
            })

    def random_mean(self, c, s, tf, t, regime, cost):
        """Random entries from the past only (a live trade can't look ahead), same regime and exits."""
        hold = None if t["target"] is not None else t["hold_bars"]
        T = t["hold_bars"]
        window = config.RANDOM_WINDOW_DAYS * 24 // config.TF_HOURS[tf]
        atr = ind.atr(c["high"], c["low"], c["close"], config.ATR_WINDOW)
        lo, hi = max(config.ATR_WINDOW, s - window), s - T - 1
        if hi <= lo:
            return None
        cand = np.arange(lo, hi)
        cand = cand[(regime[cand] == regime[s]) & ~np.isnan(atr[cand])]
        if len(cand) == 0:
            return None
        draws = self.rng.choice(cand, size=config.RANDOM_DRAWS_PER_TRADE)
        rx = scorecard.simulate_exits(c, draws, tf, atr, hold)
        nets = rx["gross"][rx["valid"]] - cost
        return float(nets.mean()) if len(nets) else None

    def alert_signals(self, conn, tf, opened, settings):
        if not opened or not settings.get(f"alert_{tf}", False):
            return
        live_only = set(config.FORWARD_ONLY_VARIANTS)
        if len(opened) == 1:
            variant, family, params, sym = opened[0]
            title, spoken = describe(family, params, sym, tf)
            tag = " (live test)" if variant in live_only else ""
            self.notify(conn, "signal", title, f"{TF_WORDS[tf].capitalize()} chart · paper trade opened{tag}",
                        symbol=sym, tf=tf, link=f"#/chart/{sym}/{tf}", speak=spoken, settings=settings)
        else:
            coins = sorted({short(s) for _, _, _, s in opened})
            title = f"{len(opened)} signals on the {TF_WORDS[tf]} close"
            body = ", ".join(coins[:8]) + (" and more" if len(coins) > 8 else "")
            self.notify(conn, "signal", title, body, tf=tf, link="#/chart",
                        speak=f"{len(opened)} new signals on the {TF_WORDS[tf]} chart", settings=settings)

    # --- price watch ---------------------------------------------------------------

    def price_watch(self, conn, settings):
        symbols = set(self.universe(conn))
        rows = self.fetch._get(config.BINANCE_SPOT, "/api/v3/ticker/price", {})
        now = self.clock()
        window = config.PRICE_WATCH_WINDOW_MIN * 60
        self.status["price_watch_at"] = self.now_ms()
        for r in rows:
            sym = r["symbol"]
            if sym not in symbols:
                continue
            price = float(r["price"])
            self.prices[sym] = price
            h = self.history[sym]
            h.append((now, price))
            while h and now - h[0][0] > window + config.PRICE_WATCH_EVERY_S:
                h.popleft()
            old = next((p for ts, p in h if now - ts <= window), None)
            span = now - h[0][0]
            if old is None or span < window * 0.75:
                continue          # not enough history yet to say "in the last 20 minutes"
            move = price / old - 1
            limit = config.PRICE_WATCH_MOVE_MAJORS if sym in config.MAJORS else config.PRICE_WATCH_MOVE
            if abs(move) < limit or not settings.get("alert_moves", True):
                continue
            if self.now_ms() - store.last_alert_time(conn, "move", sym) < config.PRICE_WATCH_COOLDOWN_MIN * 60_000:
                continue
            word = "up" if move > 0 else "down"
            self.notify(conn, "move", f"{short(sym)} {move:+.1%} in {config.PRICE_WATCH_WINDOW_MIN} min",
                        f"Now {price:g}. Price alert only, not a signal.", symbol=sym,
                        link=f"#/chart/{sym}/1h", speak=f"{short(sym)} is {word} {abs(move):.0%}",
                        settings=settings)

    # --- updates -------------------------------------------------------------------

    def update_check(self, conn, settings):
        import updater
        info = updater.check()
        self.status["update_checked_at"] = self.now_ms()
        if info.get("available") and not conn.execute(
                "SELECT 1 FROM alerts WHERE kind='update' AND body LIKE ?", (f"%{info['latest']}%",)).fetchone():
            self.notify(conn, "update", "Signal Lab update available",
                        f"Version {info['latest']} is ready to download in Settings.",
                        link="#/settings", settings=settings)
