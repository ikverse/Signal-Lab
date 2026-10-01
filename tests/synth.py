"""Synthetic candles for tests: a random walk with occasional jumps, aligned to UTC midnight."""

import numpy as np

START_MS = 1_704_067_200_000          # 1 Jan 2024 00:00 UTC, a Monday
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def candles(n, tf="1d", seed=0, symbol="TESTUSDT"):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0005, 0.02, n)
    r[rng.random(n) < 0.02] *= 5                      # a few big moves so signals fire
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.concatenate([[100.0], close[:-1]])
    wick = np.abs(rng.normal(0, 0.006, (2, n)))
    t = START_MS + np.arange(n, dtype=np.int64) * TF_MS[tf]
    return {
        "symbol": symbol, "tf": tf, "t": t,
        "open": open_, "close": close,
        "high": np.maximum(open_, close) * (1 + wick[0]),
        "low": np.minimum(open_, close) * (1 - wick[1]),
        "volume": rng.uniform(1, 2, n), "close_time": t + TF_MS[tf] - 1,
    }


def panel(coins, n, tf="1d"):
    return {f"C{i}USDT": candles(n, tf, seed=i, symbol=f"C{i}USDT") for i in range(coins)}
