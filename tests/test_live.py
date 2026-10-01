"""The live engine must make the same calls as the backtest, one candle at a time."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

import config
import live
import scorecard
import store
from backtest import compute_signals
from tests import synth


class ExitRulesMatchBacktest(unittest.TestCase):
    def test_check_exit_equals_simulate_exits(self):
        c = synth.candles(800, "1d", seed=5)
        atr = np.full(800, 3.0)
        sig = np.arange(20, 780, 7)
        ex = scorecard.simulate_exits(c, sig, "1d", atr)
        T = config.TIME_LIMIT_BARS["1d"]
        for j, s in enumerate(sig):
            if not ex["valid"][j]:
                continue
            e = s + 1
            entry = c["open"][e]
            got = live.check_exit(c, e, T, entry + config.TARGET_ATR * 3.0, entry - config.STOP_ATR * 3.0)
            self.assertIsNotNone(got)
            i, price, reason = got
            self.assertEqual(i, ex["exit_idx"][j])
            self.assertEqual(reason, ex["reason"][j])
            self.assertAlmostEqual(price, ex["exit_price"][j])

    def test_running_trade_stays_open(self):
        c = synth.candles(30, "1d", seed=1)
        e = 27                               # only 3 candles after entry, limit is 7
        self.assertIsNone(live.check_exit(c, e, 7, c["open"][e] * 10, c["open"][e] / 10))


class FakeFetch:
    """Stands in for data_binance: reveals one more stored candle each time it is asked."""

    def __init__(self, full):
        self.full = full                     # {symbol: candles}
        self.visible = {}

    def reveal(self, n):
        self.visible = {s: n for s in self.full}

    def download_klines(self, conn, symbol, tf, since_ms):
        c = self.full.get(symbol)
        if c is None or tf != "1d":
            return 0
        n = self.visible.get(symbol, 0)
        rows = [[int(c["t"][i]), c["open"][i], c["high"][i], c["low"][i], c["close"][i], 1.0,
                 int(c["close_time"][i]), 1.0] for i in range(n)]
        store.insert_candles(conn, symbol, tf, rows)
        return n

    def _get(self, base, path, params):
        c = self.full[params["symbol"]]
        i = int(np.searchsorted(c["t"], params["startTime"]))
        return [[int(c["t"][i]), c["open"][i]]] if i < len(c["t"]) else []


class EngineReplay(unittest.TestCase):
    def test_one_candle_at_a_time_matches_backtest(self):
        n, start = 700, 640
        full = {f"C{i}USDT": synth.candles(n, "1d", seed=i, symbol=f"C{i}USDT") for i in range(8)}
        full["BTCUSDT"] = synth.candles(n, "1d", seed=99, symbol="BTCUSDT")
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "t.db"
            conn = store.connect(db)
            store.save_universe(conn, "2026-01-01", [(s, 1.0) for s in full])
            fetch = FakeFetch(full)
            fetch.reveal(start)
            for s in full:
                fetch.download_klines(conn, s, "1d", 0)
            sent = []
            eng = live.Engine(fetch=fetch, notify=lambda *a, **k: sent.append((a, k)),
                              clock=lambda: full["BTCUSDT"]["t"][-1] / 1000 + 10 * 86400, db_path=db)
            eng.init_state(conn)
            settings = store.get_settings(conn)
            for k in range(start + 1, n + 1):
                fetch.reveal(k)
                eng.last_processed["1d"] = int(full["BTCUSDT"]["t"][k - 2])
                eng.process_tf(conn, "1d", settings)
            self.assertIsNone(eng.status["last_error"])
            trades = store.live_trades(conn, limit=100000)
            self.assertTrue(trades, "no live trades were opened")
            keys = [(t["variant"], t["symbol"], t["bar_time"]) for t in trades]
            self.assertEqual(len(keys), len(set(keys)), "a signal was traded twice")

            # every live trade sits on a bar where the backtest's own signals fire
            panel = {s: store.load_candles(conn, s, "1d", 0) for s in full}
            sig = {k[0]: v for k, v in compute_signals(panel, "1d").items()}
            for t in trades:
                c = panel[t["symbol"]]
                i = int(np.searchsorted(c["t"], t["bar_time"]))
                self.assertTrue(sig[t["variant"]][t["symbol"]][i], f"{t['variant']} has no signal there")
                self.assertEqual(t["entry_price"], c["open"][i + 1] if i + 1 < len(c["t"]) else t["entry_price"])

            # closed trades closed by the backtest's exit rules
            for t in [t for t in trades if t["exit_time"] is not None]:
                c = panel[t["symbol"]]
                e = int(np.searchsorted(c["t"], t["entry_time"]))
                i, price, reason = live.check_exit(c, e, t["hold_bars"], t["target"], t["stop"])
                self.assertEqual(reason, t["exit_reason"])
                self.assertAlmostEqual(price, t["exit_price"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
