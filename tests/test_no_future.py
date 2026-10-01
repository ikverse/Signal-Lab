"""No signal or trade may use data from after the moment it claims to know it."""

import unittest

import numpy as np

import backtest
import scorecard
from tests import synth


def scramble_after(panel, cut_time, seed=3):
    """Replace every candle after cut_time with wild nonsense."""
    rng = np.random.default_rng(seed)
    out = {}
    for sym, c in panel.items():
        c = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in c.items()}
        m = c["t"] > cut_time
        f = rng.uniform(0.2, 5.0, m.sum())
        for key in ("open", "high", "low", "close"):
            c[key][m] *= f
        c["high"][m] *= 1.5
        c["low"][m] *= 0.5
        out[sym] = c
    return out


class NoFutureTests(unittest.TestCase):
    def test_changing_the_future_never_changes_past_signals(self):
        for tf, coins, n in (("1d", 9, 900), ("1h", 2, 9500)):
            panel = synth.panel(coins, n, tf)
            cut = panel["C0USDT"]["t"][int(n * 0.7)]
            a = backtest.compute_signals(panel, tf)
            b = backtest.compute_signals(scramble_after(panel, cut), tf)
            k = int(n * 0.7) + 1
            for key in a:
                for sym in a[key]:
                    self.assertTrue(np.array_equal(a[key][sym][:k], b[key][sym][:k]),
                                    f"{key[0]} {sym} changed before the cut ({tf})")

    def _flat(self, n=12):
        t = synth.START_MS + np.arange(n, dtype=np.int64) * synth.TF_MS["1d"]
        one = np.full(n, 100.0)
        return {"t": t, "close_time": t + synth.TF_MS["1d"] - 1, "open": one.copy(),
                "high": one + 1, "low": one - 1, "close": one.copy()}

    def test_entry_is_next_open(self):
        c = self._flat()
        c["open"][4] = 123.0
        atr = np.full(12, 10.0)
        ex = scorecard.simulate_exits(c, [3], "1d", atr)
        self.assertEqual(ex["entry_price"][0], 123.0)

    def test_stop_assumed_first_when_both_hit_in_one_candle(self):
        c = self._flat()
        atr = np.full(12, 2.0)         # entry 100, target 104, stop 98
        c["high"][5], c["low"][5] = 110.0, 90.0
        ex = scorecard.simulate_exits(c, [3], "1d", atr)
        self.assertEqual(ex["reason"][0], "stop")
        self.assertEqual(ex["exit_price"][0], 98.0)

    def test_gap_below_stop_fills_at_the_open(self):
        c = self._flat()
        atr = np.full(12, 2.0)
        c["open"][6], c["low"][6], c["high"][6] = 90.0, 89.0, 91.0
        ex = scorecard.simulate_exits(c, [3], "1d", atr)
        self.assertEqual(ex["reason"][0], "stop")
        self.assertEqual(ex["exit_price"][0], 90.0)

    def test_trade_without_enough_future_is_invalid(self):
        c = self._flat()
        ex = scorecard.simulate_exits(c, [9], "1d", np.full(12, 2.0))
        self.assertFalse(ex["valid"][0])


if __name__ == "__main__":
    unittest.main()
