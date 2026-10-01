# Signal Lab

Scans the 30 most-traded crypto pairs on Binance for trend and momentum signals, turns every
signal into a paper trade, and keeps an honest scorecard of whether each signal beats random
entries after fees. Research tool, not financial advice. No real money is ever traded.

It runs on a Galaxy Note 9 (in Termux) as an always-on landscape app with live alerts, and on a
PC for backtests and development. Current version: see `VERSION`; history in `CHANGELOG.md`.

## Setup

In **PowerShell**, from the `signal-lab` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run the backtest

Same shell and folder:

```powershell
.\.venv\Scripts\python backtest.py
```

The first run downloads hourly, 4-hour and daily candles since 2019 for 30 coins (about 2,400
requests, roughly 20 minutes) into `data\signal_lab.db`. Later runs only fetch new candles.
Then it scores every signal and prints the scorecard. A Markdown and JSON copy is saved in
`reports\`.

Useful options:

| Option | What it does |
|---|---|
| `--skip-download` | Score the data already stored |
| `--tf 1d` | Only some timeframes (`1h`, `4h`, `1d`) |
| `--symbols BTCUSDT ETHUSDT` | Use your own coin list instead of the top 30 |
| `--no-save-trades` | Don't write every paper trade to the database (faster) |
| `--replay-cuts 10` | More cut points for the repaint check |

## Run the tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -t .
```

The tests check indicator values against hand-worked numbers, that entries use the next open
and stops are assumed first, and that **no signal changes when future data is added or
scrambled**. The backtest repeats that last check on the real data every run.

## Run the app

Same shell and folder:

```powershell
.\.venv\Scripts\python server.py
```

Then open <http://127.0.0.1:8765>. The live engine runs inside the server: after every closed
1h, 4h and daily candle it fetches the new candles, opens a paper trade for each new signal and
closes trades that hit their target, stop or time limit. `--no-engine` serves the app only.

On the phone, see **[phone/setup.md](phone/setup.md)**.

## Push and release

- **Push**: commit and push to `main`. GitHub runs the tests. Nothing reaches the phone.
- **Release**: bump `VERSION`, add the version's section to `CHANGELOG.md`, commit, then tag and
  push the tag explicitly:

  ```powershell
  git tag v0.2.1
  git push origin main
  git push origin v0.2.1
  ```

  The tag runs the tests again and, only if they pass, publishes `signal-lab-v0.2.1.zip` with its
  SHA-256 as the Latest release. The phone offers it under Settings → About, runs the new
  version's tests on the phone before switching, and keeps the previous version for Roll back.
  The database lives outside the versions and is upgraded in place by `store.MIGRATIONS`, which
  may only ever gain steps, never have one edited.

## Files

| File | Job |
|---|---|
| `config.py` | Every window, threshold, cost and exit setting |
| `data_binance.py` | Downloads candles and funding from Binance's public API (closed candles only) |
| `store.py` | SQLite storage; signals, trades and scores are append-only per run |
| `indicators.py` | Moving averages, rolling highs, ATR, returns, RSI |
| `signals_trend.py` | Trend state, Donchian breakout, time-series and cross-sectional momentum |
| `signals_intraday.py` | Big-move fade and intraday momentum (1h only) |
| `scorecard.py` | Paper trades, matched random entries, statistics, verdicts |
| `backtest.py` | The command: download, replay, repaint check, score, report |
| `report.py` | Prints the scorecard and saves it |
| `live.py` | The live engine: candle closes, live paper trades, price watch, update checks |
| `alerts.py` | Phone notifications and spoken alerts (Termux:API); prints on a PC |
| `server.py` | Local web server and JSON API for the app; runs the engine |
| `updater.py` | Checks, downloads, self-tests, installs and rolls back GitHub releases |
| `app/` | The landscape app: chart, scorecard, Learn, alerts, settings; libraries in `app/vendor/` |
| `phone/` | Setup steps and `start.sh` for Termux |
| `docs/signals/` | One plain-language page per signal, with its flow and evidence |
| `docs/basics/` | Candles, fees, and how the scorecard judges a signal |

## Doc placeholders

The docs contain placeholders the app fills in when it shows them:

- `{{NAME}}` is replaced with the value of `NAME` from `config.py`, so the docs always show the
  settings the engine is really using.
- `{{scorecard:family}}` and `{{examples:family}}` are replaced with that signal's live
  scorecard numbers and a real winning and losing trade from the database.

## Honest limits

- The coin list is today's most-traded pairs, so coins that collapsed or were delisted are
  missing (survivorship bias). Backtest results look better than reality.
- Every signal variant ever tried is recorded in the `variants` table and counted in the
  multiple-testing correction. Tweaking settings until something looks good is exactly the
  trap this guards against.
- An "Edge" verdict still needs months of forward paper trading before it means anything.
