"""Indicator values checked against numbers worked out by hand."""

import unittest

import numpy as np

import indicators as ind


class IndicatorTests(unittest.TestCase):
    def assertSeries(self, got, want, places=6):
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            if w is None:
                self.assertTrue(np.isnan(g), f"expected NaN, got {g}")
            else:
                self.assertAlmostEqual(g, w, places=places)

    def test_sma(self):
        self.assertSeries(ind.sma(np.array([1, 2, 3, 4, 5.0]), 3), [None, None, 2, 3, 4])

    def test_rolling_max_prior_excludes_current_bar(self):
        self.assertSeries(ind.rolling_max_prior(np.array([1, 3, 2, 5, 4.0]), 2),
                          [None, None, 3, 3, 5])

    def test_true_range_and_atr(self):
        high = np.array([10, 12, 11.0])
        low = np.array([9, 10, 8.0])
        close = np.array([9.5, 11, 9.0])
        # bar 1: max(12-10, |12-9.5|, |10-9.5|) = 2.5 ; bar 2: max(3, |11-11|, |8-11|) = 3
        self.assertSeries(ind.true_range(high, low, close), [1, 2.5, 3])
        self.assertSeries(ind.atr(high, low, close, 2), [None, 1.75, 2.75])

    def test_pct_return(self):
        self.assertSeries(ind.pct_return(np.array([100, 110, 121.0]), 1), [None, 0.1, 0.1])
        self.assertSeries(ind.pct_return(np.array([100, 110, 121.0]), 2), [None, None, 0.21])

    def test_rsi_by_hand(self):
        close = np.array([44, 44.34, 44.09, 44.15, 43.61, 44.33])
        # n=2: seed gain 0.17 loss 0.125 -> 57.627; then Wilder smoothing step by step:
        # (0.115, 0.0625) -> 64.789; (0.0575, 0.30125) -> 16.028; (0.38875, 0.150625) -> 72.074
        self.assertSeries(ind.rsi(close, 2), [None, None, 57.6271, 64.7887, 16.0279, 72.0740],
                          places=3)

    def test_rsi_all_rising_is_100(self):
        self.assertEqual(ind.rsi(np.arange(1, 30, dtype=float), 14)[-1], 100.0)

    def test_crossed_above(self):
        a = np.array([1, 2, 3, 2, 4.0])
        b = np.array([2, 2, 2, 2, 2.0])
        self.assertEqual(ind.crossed_above(a, b).tolist(), [False, False, True, False, True])

    def test_rolling_std(self):
        self.assertSeries(ind.rolling_std(np.array([1, 3, 5.0]), 2), [None, 1, 1])


if __name__ == "__main__":
    unittest.main()
