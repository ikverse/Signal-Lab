"""Every API answer the app relies on, against a scratch database."""

import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import config
import server
import store
from tests import synth


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (config.DB_PATH, config.DATA_DIR)
        config.DATA_DIR = Path(cls.tmp.name)
        config.DB_PATH = config.DATA_DIR / "t.db"
        conn = store.connect()
        store.save_universe(conn, "2026-01-01", [("BTCUSDT", 1.0), ("ETHUSDT", 1.0)])
        for sym in ("BTCUSDT", "ETHUSDT"):
            for tf in ("1h", "1d"):
                c = synth.candles(400, tf, seed=len(sym))
                # recent timestamps, so the watchlist's "last 3 days" window finds them
                shift = (int(__import__("time").time() * 1000) // 3_600_000 * 3_600_000) - int(c["t"][-1])
                rows = [[int(c["t"][i]) + shift, c["open"][i], c["high"][i], c["low"][i], c["close"][i], 1.0,
                         int(c["close_time"][i]) + shift, 1.0] for i in range(400)]
                store.insert_candles(conn, sym, tf, rows)
        conn.close()
        cls.srv = server.make_server(port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        config.DB_PATH, config.DATA_DIR = cls.saved
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read())

    def test_status(self):
        s = self.get("/api/status")
        self.assertEqual(s["app"], "Signal Lab")
        self.assertEqual(s["version"], config.VERSION)
        self.assertIn("settings", s)

    def test_watchlist(self):
        w = self.get("/api/watchlist")
        self.assertEqual([x["symbol"] for x in w], ["BTCUSDT", "ETHUSDT"])
        self.assertTrue(all(x["price"] > 0 for x in w))

    def test_candles(self):
        rows = self.get("/api/candles?symbol=BTCUSDT&tf=1d&limit=50")
        self.assertEqual(len(rows), 50)
        self.assertEqual(len(rows[0]), 6)

    def test_every_doc_renders_with_no_unfilled_setting(self):
        index = self.get("/api/docs")
        self.assertGreaterEqual(len(index), 9)
        for d in index:
            md = self.get(f"/api/docs/{d['group']}/{d['name']}")["markdown"]
            self.assertFalse(re.search(r"\{\{[A-Z_]+\}\}", md), f"unfilled setting in {d['name']}")
            self.assertNotIn("{{scorecard:", md)

    def test_settings_round_trip(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/settings",
                                     data=json.dumps({"alert_1h": True, "not_a_setting": 1}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            s = json.loads(r.read())
        self.assertTrue(s["alert_1h"])
        self.assertNotIn("not_a_setting", s)

    def test_scorecard_and_lists_answer_on_an_empty_record(self):
        self.assertEqual(self.get("/api/scorecard")["scores"], [])
        self.assertEqual(self.get("/api/trades"), [])
        self.assertEqual(self.get("/api/alerts"), [])

    def test_static_files_cannot_escape_the_app_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/../config.py")
        self.assertEqual(e.exception.code, 404)
        e.exception.close()

    def test_index_page_is_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r:
            self.assertIn(b"Signal Lab", r.read())


if __name__ == "__main__":
    unittest.main()
