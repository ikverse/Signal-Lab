# How the scorecard judges a signal

The scorecard's job is to answer one question honestly: **does this signal do better than
buying at a random moment?** Most signals don't. Finding that out on paper costs nothing.

## Every signal becomes a paper trade

- **Entry:** the open of the candle after the signal.
- **Exit:** whichever comes first: the target ({{TARGET_ATR}} × ATR above entry), the stop
  ({{STOP_ATR}} × ATR below entry), or the time limit ({{TIME_LIMIT_BARS}} candles). ATR is the
  coin's average candle range over the last {{ATR_WINDOW}} candles, so targets and stops scale
  with how jumpy the coin is.
- If the target and the stop are both touched inside the same candle, the scorecard assumes
  the stop came first. If the price gaps past a level, the trade fills at the open, not at the
  level.
- Costs are taken off every trade (see Fees).
- While a trade on a coin is open, new signals for that coin are ignored, so one move is never
  counted twice.

## The comparison: random entries

For every trade, the scorecard also makes {{RANDOM_DRAWS_PER_TRADE}} random entries on the same
coin, within {{RANDOM_WINDOW_DAYS}} days of the signal, in the same market regime (BTC above or
below its {{REGIME_MA_DAYS}}-day average), with exactly the same exits and costs.

This matters because crypto mostly went up over the years, and stops and targets shape the
win rate on their own. A signal with a 45% win rate can be good if random entries win 38% of
the time, and useless if random entries win 46%.

| Column | Meaning |
|---|---|
| Win % | Share of paper trades that made money after costs |
| Random % | The same for the random entries |
| Lift | Win % minus Random %, in percentage points |
| Avg net | Average return per trade after costs |
| Excess | Average return per trade minus its random entries' average |
| t | How sure we can be that Excess is above zero. Counted by calendar week, so ten coins breaking out on one day count as one piece of evidence |
| Holm p | The chance of a result this good by luck, corrected for every signal variant ever tried |

## Fixed holding periods

Besides the target-and-stop trade, every signal is also checked at fixed holding periods
(for example 3, 7, 14 and 30 days on daily candles), each compared with the random entries
held for the same time. This shows whether a signal has an edge that the stop is cutting off.
For example, a breakout can show +14% after 30 days, but if random entries made +13% over the
same days, the signal only added 1%. These checks are not corrected for multiple testing, so
treat them as clues, not verdicts.

## Verdicts

| Verdict | Meaning |
|---|---|
| No verdict | Fewer than 30 trades: too early to say anything |
| No edge | Not distinguishable from random entries |
| Losing | Clearly worse than random (t at or below {{LOSING_T}}) |
| Edge | t at or above {{EDGE_T}} **and** Holm p below {{ALPHA}} |

Next to the verdict, the number of trades sets how firm it is: under 100 is an early read,
100–299 is provisional, 300 or more is meaningful.

## Why the bar is set so high

Testing many signals guarantees that some look good by luck. Published trading signals also
tend to lose about half their strength after they become known. So the scorecard counts every
variant ever tried, corrects for all of them, and treats even an "Edge" as something to
confirm with months of live paper trading before trusting it.

## Known limits of the backtest

- The coin list is today's most-traded coins, so coins that collapsed or were delisted are
  missing. This makes every result look better than reality.
- The past is one path. A signal that worked in 2020–2021 can fail in the next market.
- Forward paper trading, started in Phase 2, is the real test.
