# Fees and slippage

Every real trade costs money twice: once to buy and once to sell. On top of the exchange fee,
the price you actually get is usually a little worse than the price on the screen (slippage),
especially for smaller coins.

The scorecard charges every paper trade a round-trip cost:

| Coins | Round-trip cost |
|---|---|
| BTC and ETH | {{COST_MAJORS}} |
| All other coins | {{COST_OTHERS}} |

These are based on Binance's entry-level spot fee of 0.10% per side, plus an allowance for
slippage. [Binance fee schedule](https://www.binance.com/en/fee/schedule)

## Why this matters so much

A small edge disappears fast. A 0.20% round trip already equals 44% of Bitcoin's average 3-day
return since 2017. A signal held for one hour has to beat its cost in a single hour, which is
very hard. That is why the scorecard reports every number **after** costs, and why short
timeframes need a much larger raw edge to survive.
