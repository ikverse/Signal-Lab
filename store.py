"""SQLite storage.

Candles from closed bars never change, so they are inserted once and ignored after.
Signals, trades and scores are append-only: each backtest run adds rows under its own
run_id and nothing is ever updated or deleted. The variants table remembers every
signal variant ever tried, which is what the multiple-testing correction counts.
"""

import json
import sqlite3
import time

import numpy as np

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT, tf TEXT, open_time INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume REAL, quote_volume REAL,
    close_time INTEGER,
    PRIMARY KEY (symbol, tf, open_time)
);
CREATE TABLE IF NOT EXISTS funding (
    symbol TEXT, funding_time INTEGER, rate REAL,
    PRIMARY KEY (symbol, funding_time)
);
CREATE TABLE IF NOT EXISTS universe (
    snapshot_date TEXT, rank INTEGER, symbol TEXT, quote_volume REAL,
    PRIMARY KEY (snapshot_date, symbol)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER, params TEXT
);
CREATE TABLE IF NOT EXISTS variants (
    variant TEXT PRIMARY KEY, family TEXT, tf TEXT, params TEXT,
    first_run INTEGER, first_seen_at INTEGER
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER, variant TEXT, symbol TEXT, tf TEXT,
    bar_time INTEGER, detected_at INTEGER, regime INTEGER
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER, signal_id INTEGER, variant TEXT, symbol TEXT, tf TEXT,
    entry_time INTEGER, entry_price REAL, exit_time INTEGER, exit_price REAL,
    exit_reason TEXT, bars_held INTEGER, gross REAL, net REAL,
    random_mean REAL, excess REAL, horizons TEXT
);
CREATE TABLE IF NOT EXISTS scores (
    run_id INTEGER, variant TEXT, tf TEXT, family TEXT,
    n INTEGER, hit REAL, random_hit REAL, mean REAL, median REAL, random_mean REAL,
    excess REAL, t REAL, t_cluster REAL, p REAL, p_holm REAL, q_bh REAL,
    profit_factor REAL, verdict TEXT, details TEXT,
    PRIMARY KEY (run_id, variant)
);
"""


# Each step upgrades the database from the version before it. A new version of the app may
# only ever add a step here, never edit one, because phones in the field are at every version.
MIGRATIONS = {
    2: """
    CREATE TABLE IF NOT EXISTS live_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant TEXT, family TEXT, symbol TEXT, tf TEXT,
        bar_time INTEGER, detected_at INTEGER, regime INTEGER,
        entry_time INTEGER, entry_price REAL, target REAL, stop REAL,
        hold_bars INTEGER, exit_due INTEGER, opened_at INTEGER,
        UNIQUE (variant, symbol, bar_time)
    );
    CREATE TABLE IF NOT EXISTS live_exits (
        trade_id INTEGER PRIMARY KEY,
        exit_time INTEGER, exit_price REAL, exit_reason TEXT, bars_held INTEGER,
        gross REAL, net REAL, random_mean REAL, excess REAL, closed_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER, kind TEXT, symbol TEXT, tf TEXT, title TEXT, body TEXT, link TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    """,
}
SCHEMA_VERSION = max(MIGRATIONS)


def connect(path=None, check_same_thread=True):
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=check_same_thread, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def migrate(conn):
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version in sorted(MIGRATIONS):
        if version > current:
            conn.executescript(MIGRATIONS[version])
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()


# --- Candles and funding --------------------------------------------------------

def insert_candles(conn, symbol, tf, rows):
    """rows: Binance kline lists. Only closed candles should be passed in."""
    conn.executemany(
        "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(symbol, tf, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
          float(r[5]), float(r[7]), int(r[6])) for r in rows],
    )
    conn.commit()


def last_open_time(conn, symbol, tf):
    row = conn.execute(
        "SELECT MAX(open_time) FROM candles WHERE symbol=? AND tf=?", (symbol, tf)
    ).fetchone()
    return row[0]


def load_candles(conn, symbol, tf, since_ms=0):
    rows = conn.execute(
        "SELECT open_time, open, high, low, close, volume, close_time FROM candles "
        "WHERE symbol=? AND tf=? AND open_time>=? ORDER BY open_time",
        (symbol, tf, since_ms),
    ).fetchall()
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    return {
        "symbol": symbol, "tf": tf,
        "t": a[:, 0].astype(np.int64), "open": a[:, 1], "high": a[:, 2],
        "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5],
        "close_time": a[:, 6].astype(np.int64),
    }


def insert_funding(conn, symbol, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO funding VALUES (?,?,?)",
        [(symbol, int(r["fundingTime"]), float(r["fundingRate"])) for r in rows],
    )
    conn.commit()


def last_funding_time(conn, symbol):
    return conn.execute(
        "SELECT MAX(funding_time) FROM funding WHERE symbol=?", (symbol,)
    ).fetchone()[0]


# --- Universe -------------------------------------------------------------------

def save_universe(conn, snapshot_date, ranked):
    """One snapshot per day; picking again on the same day replaces that day's list."""
    conn.execute("DELETE FROM universe WHERE snapshot_date=?", (snapshot_date,))
    conn.executemany(
        "INSERT OR IGNORE INTO universe VALUES (?,?,?,?)",
        [(snapshot_date, i + 1, s, v) for i, (s, v) in enumerate(ranked)],
    )
    conn.commit()


def latest_universe(conn):
    row = conn.execute("SELECT MAX(snapshot_date) FROM universe").fetchone()
    if not row or not row[0]:
        return []
    return [r[0] for r in conn.execute(
        "SELECT symbol FROM universe WHERE snapshot_date=? ORDER BY rank", (row[0],)
    )]


# --- Runs, variants, results ----------------------------------------------------

def start_run(conn, params):
    cur = conn.execute(
        "INSERT INTO runs (started_at, params) VALUES (?,?)",
        (int(time.time() * 1000), json.dumps(params, sort_keys=True)),
    )
    conn.commit()
    return cur.lastrowid


def register_variant(conn, run_id, variant, family, tf, params):
    conn.execute(
        "INSERT OR IGNORE INTO variants VALUES (?,?,?,?,?,?)",
        (variant, family, tf, json.dumps(params, sort_keys=True), run_id,
         int(time.time() * 1000)),
    )
    conn.commit()


def variants_ever_tried(conn):
    return conn.execute("SELECT COUNT(*) FROM variants").fetchone()[0]


def insert_results(conn, run_id, variant, tf, trades):
    """trades: list of dicts from scorecard.simulate. Writes a signal row and a trade row each."""
    for tr in trades:
        cur = conn.execute(
            "INSERT INTO signals (run_id, variant, symbol, tf, bar_time, detected_at, regime) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, variant, tr["symbol"], tf, tr["bar_time"], tr["detected_at"], tr["regime"]),
        )
        conn.execute(
            "INSERT INTO trades (run_id, signal_id, variant, symbol, tf, entry_time, entry_price, "
            "exit_time, exit_price, exit_reason, bars_held, gross, net, random_mean, excess, horizons) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, cur.lastrowid, variant, tr["symbol"], tf, tr["entry_time"], tr["entry_price"],
             tr["exit_time"], tr["exit_price"], tr["exit_reason"], tr["bars_held"], tr["gross"],
             tr["net"], tr["random_mean"], tr["excess"], json.dumps(tr["horizons"])),
        )
    conn.commit()


def insert_score(conn, run_id, s):
    conn.execute(
        "INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, s["variant"], s["tf"], s["family"], s["n"], s["hit"], s["random_hit"],
         s["mean"], s["median"], s["random_mean"], s["excess"], s["t"], s["t_cluster"],
         s["p"], s["p_holm"], s["q_bh"], s["profit_factor"], s["verdict"],
         json.dumps(s["details"])),
    )
    conn.commit()


# --- Live paper trades (Phase 2) --------------------------------------------------
# A trade is opened with one row in live_trades and closed with one row in live_exits.
# Neither table is ever updated, so the log can't be rewritten after the fact.

def open_live_trade(conn, t):
    cur = conn.execute(
        "INSERT OR IGNORE INTO live_trades (variant, family, symbol, tf, bar_time, detected_at, regime, "
        "entry_time, entry_price, target, stop, hold_bars, exit_due, opened_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (t["variant"], t["family"], t["symbol"], t["tf"], t["bar_time"], t["detected_at"], t["regime"],
         t["entry_time"], t["entry_price"], t["target"], t["stop"], t["hold_bars"], t["exit_due"],
         int(time.time() * 1000)),
    )
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def has_open_trade(conn, variant, symbol):
    return conn.execute(
        "SELECT 1 FROM live_trades t LEFT JOIN live_exits x ON x.trade_id = t.id "
        "WHERE t.variant=? AND t.symbol=? AND x.trade_id IS NULL LIMIT 1", (variant, symbol)
    ).fetchone() is not None


def close_live_trade(conn, trade_id, x):
    conn.execute(
        "INSERT OR IGNORE INTO live_exits VALUES (?,?,?,?,?,?,?,?,?,?)",
        (trade_id, x["exit_time"], x["exit_price"], x["exit_reason"], x["bars_held"], x["gross"],
         x["net"], x.get("random_mean"), x.get("excess"), int(time.time() * 1000)),
    )
    conn.commit()


LIVE_COLUMNS = ["id", "variant", "family", "symbol", "tf", "bar_time", "detected_at", "regime",
                "entry_time", "entry_price", "target", "stop", "hold_bars", "exit_due", "opened_at",
                "exit_time", "exit_price", "exit_reason", "bars_held", "gross", "net", "random_mean",
                "excess", "closed_at"]


def live_trades(conn, status="all", symbol=None, limit=500):
    """status: 'open', 'closed' or 'all'. Newest first, as dicts."""
    where, args = [], []
    if status == "open":
        where.append("x.trade_id IS NULL")
    elif status == "closed":
        where.append("x.trade_id IS NOT NULL")
    if symbol:
        where.append("t.symbol=?")
        args.append(symbol)
    sql = ("SELECT t.id, t.variant, t.family, t.symbol, t.tf, t.bar_time, t.detected_at, t.regime, "
           "t.entry_time, t.entry_price, t.target, t.stop, t.hold_bars, t.exit_due, t.opened_at, "
           "x.exit_time, x.exit_price, x.exit_reason, x.bars_held, x.gross, x.net, x.random_mean, "
           "x.excess, x.closed_at FROM live_trades t LEFT JOIN live_exits x ON x.trade_id = t.id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.detected_at DESC LIMIT ?"
    return [dict(zip(LIVE_COLUMNS, r)) for r in conn.execute(sql, (*args, limit))]


# --- Alerts and settings ----------------------------------------------------------

def add_alert(conn, kind, title, body, symbol=None, tf=None, link=None):
    conn.execute("INSERT INTO alerts (ts, kind, symbol, tf, title, body, link) VALUES (?,?,?,?,?,?,?)",
                 (int(time.time() * 1000), kind, symbol, tf, title, body, link))
    conn.commit()


def recent_alerts(conn, limit=100):
    cols = ["id", "ts", "kind", "symbol", "tf", "title", "body", "link"]
    return [dict(zip(cols, r)) for r in conn.execute(
        "SELECT id, ts, kind, symbol, tf, title, body, link FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]


def last_alert_time(conn, kind, symbol):
    row = conn.execute("SELECT MAX(ts) FROM alerts WHERE kind=? AND symbol=?", (kind, symbol)).fetchone()
    return row[0] or 0


def get_settings(conn):
    s = dict(config.SETTINGS_DEFAULTS)
    for k, v in conn.execute("SELECT key, value FROM settings"):
        s[k] = json.loads(v)
    return s


def set_settings(conn, values):
    for k, v in values.items():
        if k in config.SETTINGS_DEFAULTS:
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, json.dumps(v)))
    conn.commit()


# --- Backtest results, for the app -------------------------------------------------

def latest_scores(conn):
    row = conn.execute("SELECT MAX(run_id) FROM scores").fetchone()
    if not row or row[0] is None:
        return None, []
    cols = ["run_id", "variant", "tf", "family", "n", "hit", "random_hit", "mean", "median",
            "random_mean", "excess", "t", "t_cluster", "p", "p_holm", "q_bh", "profit_factor",
            "verdict", "details"]
    out = []
    for r in conn.execute("SELECT * FROM scores WHERE run_id=?", (row[0],)):
        d = dict(zip(cols, r))
        d["details"] = json.loads(d["details"]) if d["details"] else {}
        out.append(d)
    return row[0], out


def latest_trades_run(conn):
    """The newest backtest run that saved its trades (runs with --no-save-trades don't)."""
    row = conn.execute("SELECT MAX(run_id) FROM trades").fetchone()
    return row[0] if row else None


def backtest_trades(conn, run_id, symbol=None, tf=None, variant=None, family=None, limit=200):
    where, args = ["run_id=?"], [run_id]
    for col, val in (("symbol", symbol), ("tf", tf), ("variant", variant)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    if family:
        where.append("variant IN (SELECT variant FROM variants WHERE family=?)")
        args.append(family)
    cols = ["variant", "symbol", "tf", "entry_time", "entry_price", "exit_time", "exit_price",
            "exit_reason", "bars_held", "gross", "net", "excess"]
    sql = (f"SELECT {', '.join(cols)} FROM trades WHERE {' AND '.join(where)} "
           "ORDER BY entry_time DESC LIMIT ?")
    return [dict(zip(cols, r)) for r in conn.execute(sql, (*args, limit))]
