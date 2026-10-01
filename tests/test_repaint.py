"""The repaint check: signals computed on history cut off at time T must match the
full-history signals for every bar up to T, for every signal on every timeframe."""

import unittest

import numpy as np

import backtest
from tests import synth


class RepaintTests(unittest.TestCase):
    def check(self, panel, tf, cuts):
        full = backtest.compute_signals(panel, tf)
        self.assertTrue(any(f.any() for by in full.values() for f in by.values()),
                        "test data produced no signals at all")
        rng = np.random.default_rng(1)
        done, bad = backtest.repaint_check(panel, tf, full, cuts, rng)
        self.assertGreater(done, 0)
        self.assertEqual(bad, [])

    def test_daily_including_cross_sectional(self):
        panel = synth.panel(coins=9, n=900, tf="1d")
        self.check(panel, "1d", cuts=12)
        xs = [k for k in backtest.compute_signals(panel, "1d") if k[1] == "xs_momentum"]
        self.assertTrue(xs, "cross-sectional momentum was not exercised")

    def test_hourly_including_intraday(self):
        panel = synth.panel(coins=2, n=9500, tf="1h")
        self.check(panel, "1h", cuts=4)

    def test_four_hour(self):
        self.check(synth.panel(coins=3, n=3000, tf="4h"), "4h", cuts=5)


if __name__ == "__main__":
    unittest.main()
