# Candles

Every chart in the app is made of candles. One candle sums up the trading in one period:
one hour on a **1h** chart, four hours on **4h**, one day on **1D**.

| Part | Meaning |
|---|---|
| Open | First price of the period |
| High | Highest price reached |
| Low | Lowest price reached |
| Close | Last price of the period |
| Volume | How much was traded |

A green candle closed higher than it opened; a red one closed lower. The thin lines above and
below the body (the wicks) show how far the price travelled before coming back.

## Why the app waits for the close

Until a candle closes, its high, low and close keep changing. A breakout that looks real at
14:30 can be gone by 15:00. So every signal is checked **only when a candle has closed**, and
the paper trade enters at the **next** candle's open, the first price anyone could actually
have traded at.

Daily candles close at 00:00 UTC, which is 02:00 or 03:00 in Egypt depending on daylight saving.

## Timeframes

The same signal can be run on hourly, 4-hour and daily candles. Shorter candles give more
signals but more noise, and fees take a bigger bite out of each trade. Most of the published
evidence uses daily candles. The scorecard keeps each timeframe separate so you can see which
one, if any, works.
