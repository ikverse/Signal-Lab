"""The app's local web server, with the live engine running in the same process.

    python server.py                 # engine + app at http://127.0.0.1:8765
    python server.py --no-engine     # app only, against the data already stored

It listens on 127.0.0.1 only, so nothing outside the phone can reach it. The page in app/
asks it for JSON; nothing in the page talks to Binance directly.
"""

import argparse
import json
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import config
import store
import updater

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("font/woff2", ".woff2")

APP_DIR = config.ROOT / "app"
DOCS_DIR = config.ROOT / "docs"
RESTART_CODE = 3            # start.sh restarts the server when it exits with this
ENGINE = None               # set by main(); None when run with --no-engine
UPDATE_JOB = {"busy": None, "error": None, "done": None}


# --- Docs ---------------------------------------------------------------------------

def _fmt(v):
    if isinstance(v, float) and v < 0.05:
        return f"{v:.2%}"
    if isinstance(v, (list, tuple, set)):
        return ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        return " · ".join(f"{k} {x}" for k, x in v.items())
    return f"{v:g}" if isinstance(v, float) else str(v)


def render_doc(text):
    """Fill {{NAME}} from config; turn the live placeholders into elements the page fills in."""
    def sub(m):
        key = m.group(1)
        if key.startswith("scorecard:"):
            return f'<div class="doc-live" data-kind="scorecard" data-family="{key[10:]}"></div>'
        if key.startswith("examples:"):
            return f'<div class="doc-live" data-kind="examples" data-family="{key[9:]}"></div>'
        return _fmt(getattr(config, key)) if hasattr(config, key) else m.group(0)
    return re.sub(r"\{\{([A-Za-z0-9_:]+)\}\}", sub, text)


def docs_index():
    out = []
    for group in ("signals", "basics"):
        for p in sorted((DOCS_DIR / group).glob("*.md")):
            first = p.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
            out.append({"group": group, "name": p.stem, "title": first})
    return out


# --- Data for the screens -------------------------------------------------------------

def _candles(conn, symbol, tf, limit, end=None):
    c = store.load_candles(conn, symbol, tf, 0)
    if c is None:
        return []
    k = len(c["t"]) if end is None else int(np.searchsorted(c["t"], int(end), side="right"))
    lo = max(0, k - limit)
    return [[int(c["t"][i]), c["open"][i], c["high"][i], c["low"][i], c["close"][i], c["volume"][i]]
            for i in range(lo, k)]


def watchlist(conn):
    open_by = {}
    for t in store.live_trades(conn, status="open"):
        open_by.setdefault(t["symbol"], set()).add(t["tf"])
    out = []
    for sym in store.latest_universe(conn):
        c = store.load_candles(conn, sym, "1h", int(time.time() * 1000) - 3 * 86_400_000)
        if c is None or len(c["t"]) < 25:
            continue
        live = ENGINE.prices.get(sym) if ENGINE else None
        price = live or float(c["close"][-1])
        out.append({"symbol": sym, "price": price, "change_24h": price / float(c["close"][-25]) - 1,
                    "active": sorted(open_by.get(sym, set()))})
    return out


def live_summary(conn):
    closed = [t for t in store.live_trades(conn, status="closed", limit=100000)]
    by = {}
    for t in closed:
        d = by.setdefault(t["variant"], {"n": 0, "wins": 0, "net": 0.0, "excess": [], "tf": t["tf"]})
        d["n"] += 1
        d["wins"] += t["net"] > 0
        d["net"] += t["net"]
        if t["excess"] is not None:
            d["excess"].append(t["excess"])
    for d in by.values():
        d["hit"] = d["wins"] / d["n"] if d["n"] else None
        d["mean"] = d["net"] / d["n"] if d["n"] else None
        d["mean_excess"] = float(np.mean(d["excess"])) if d["excess"] else None
        del d["excess"], d["wins"]
    curve, total = [], 0.0
    for t in sorted(closed, key=lambda t: t["exit_time"]):
        total += t["net"]
        curve.append([t["exit_time"], total])
    return {"variants": by, "equity": curve, "closed": len(closed),
            "open": len(store.live_trades(conn, status="open", limit=100000))}


def scorecard_payload(conn):
    run_id, scores = store.latest_scores(conn)
    for s in scores:
        s["details"].pop("excess_ci95", None)
    return {"run_id": run_id, "scores": scores, "live": live_summary(conn),
            "forward_only": sorted(config.FORWARD_ONLY_VARIANTS)}


def examples(conn, family):
    """The best and the worst backtest trade of a family, for its Learn page."""
    run = store.latest_trades_run(conn)
    if run is None:
        return {}
    rows = store.backtest_trades(conn, run, family=family, tf="1d", limit=5000) or \
        store.backtest_trades(conn, run, family=family, limit=5000)
    wins = [r for r in rows if r["exit_reason"] == "target"]
    losses = [r for r in rows if r["exit_reason"] == "stop"]
    pick = {}
    if wins:
        pick["win"] = max(wins, key=lambda r: r["net"])
    if losses:
        pick["loss"] = min(losses, key=lambda r: r["net"])
    return pick


def chart_overlays(conn, symbol, tf):
    live = [t for t in store.live_trades(conn, symbol=symbol, limit=50) if t["tf"] == tf]
    run = store.latest_trades_run(conn)
    past = store.backtest_trades(conn, run, symbol=symbol, tf=tf, limit=40) if run else []
    return {"live": live, "backtest": past}


def status_payload(conn):
    return {
        "app": "Signal Lab", "version": updater.current_version(),
        "engine": ENGINE.status if ENGINE else None, "settings": store.get_settings(conn),
        "timeframes": config.TIMEFRAMES, "idle_return_s": config.IDLE_RETURN_S,
        "pixel_shift_s": config.PIXEL_SHIFT_S, "update": updater.summary(), "update_job": UPDATE_JOB,
        "universe": store.latest_universe(conn),
    }


# --- Updates (slow steps run in the background; the page polls status) -----------------

def _run_update(action):
    UPDATE_JOB.update(busy=action, error=None, done=None)
    try:
        if action == "check":
            updater.check()
        elif action == "download":
            updater.download()
        elif action == "install":
            v = updater.install()
            UPDATE_JOB["done"] = f"Installed {v}. Restarting…"
            threading.Timer(1.5, lambda: os._exit(RESTART_CODE)).start()
        elif action == "rollback":
            v = updater.rollback()
            UPDATE_JOB["done"] = f"Back on {v}. Restarting…"
            threading.Timer(1.5, lambda: os._exit(RESTART_CODE)).start()
    except Exception as e:
        UPDATE_JOB["error"] = str(e)
    finally:
        UPDATE_JOB["busy"] = None


# --- HTTP -----------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "SignalLab"

    def log_message(self, fmt, *args):     # keep the Termux console quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, default=_default).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, rel):
        path = (APP_DIR / rel).resolve()
        if APP_DIR.resolve() not in path.parents or not path.is_file():
            return self._json({"error": "not found"}, 404)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        p = url.path
        if not p.startswith("/api/"):
            return self._static("index.html" if p in ("/", "") else p.lstrip("/"))
        conn = store.connect()
        try:
            if p == "/api/status":
                return self._json(status_payload(conn))
            if p == "/api/watchlist":
                return self._json(watchlist(conn))
            if p == "/api/candles":
                return self._json(_candles(conn, q["symbol"], q.get("tf", "1d"),
                                           min(int(q.get("limit", 400)), 3000), q.get("end")))
            if p == "/api/overlays":
                return self._json(chart_overlays(conn, q["symbol"], q.get("tf", "1d")))
            if p == "/api/signals":
                return self._json(store.live_trades(conn, limit=int(q.get("limit", 50))))
            if p == "/api/trades":
                return self._json(store.live_trades(conn, status=q.get("status", "all"),
                                                    limit=int(q.get("limit", 500))))
            if p == "/api/scorecard":
                return self._json(scorecard_payload(conn))
            if p == "/api/backtest_trades":
                run = store.latest_trades_run(conn)
                return self._json(store.backtest_trades(conn, run, variant=q.get("variant"),
                                                        limit=int(q.get("limit", 100))) if run else [])
            if p == "/api/alerts":
                return self._json(store.recent_alerts(conn))
            if p == "/api/settings":
                return self._json(store.get_settings(conn))
            if p == "/api/docs":
                return self._json(docs_index())
            m = re.fullmatch(r"/api/docs/(signals|basics)/([a-z_]+)", p)
            if m:
                f = DOCS_DIR / m.group(1) / f"{m.group(2)}.md"
                if not f.exists():
                    return self._json({"error": "not found"}, 404)
                return self._json({"markdown": render_doc(f.read_text(encoding="utf-8"))})
            if p == "/api/examples":
                return self._json(examples(conn, q["family"]))
            if p == "/api/update":
                return self._json({**updater.summary(), "job": UPDATE_JOB})
            return self._json({"error": "not found"}, 404)
        except KeyError as e:
            return self._json({"error": f"missing {e}"}, 400)
        finally:
            conn.close()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        if p == "/api/settings":
            conn = store.connect()
            try:
                store.set_settings(conn, body)
                return self._json(store.get_settings(conn))
            finally:
                conn.close()
        m = re.fullmatch(r"/api/update/(check|download|install|rollback)", p)
        if m:
            if UPDATE_JOB["busy"]:
                return self._json({"error": f"Busy: {UPDATE_JOB['busy']}"}, 409)
            threading.Thread(target=_run_update, args=(m.group(1),), daemon=True).start()
            return self._json({"started": m.group(1)})
        return self._json({"error": "not found"}, 404)


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def make_server(port=None):
    return ThreadingHTTPServer((config.SERVER_HOST, port or config.SERVER_PORT), Handler)


def main(argv=None):
    global ENGINE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-engine", action="store_true")
    ap.add_argument("--port", type=int, default=config.SERVER_PORT)
    args = ap.parse_args(argv)
    if not args.no_engine:
        import live
        ENGINE = live.Engine()
        threading.Thread(target=ENGINE.run_forever, daemon=True, name="engine").start()
    srv = make_server(args.port)
    print(f"Signal Lab {updater.current_version()} on http://{config.SERVER_HOST}:{args.port}"
          f"{'' if ENGINE else ' (engine off)'}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
