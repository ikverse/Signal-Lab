"""Every tunable number in Signal Lab lives here.

The Learn pages read their "Settings" section from this file, so changing a value
here changes what the docs say. Nothing else in the code should hard-code a window,
threshold or cost.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "0.0.0"

# On the phone, SIGNAL_LAB_HOME is ~/signal-lab: the code runs from versions/vX.Y.Z/ and the
# database lives in data/ beside it, so installing a new version never touches it.
# On the PC it is unset and everything lives inside the project folder.
HOME = Path(os.environ["SIGNAL_LAB_HOME"]) if os.environ.get("SIGNAL_LAB_HOME") else None
DATA_DIR = (HOME or ROOT) / "data"
DB_PATH = DATA_DIR / "signal_lab.db"
REPORTS_DIR = (HOME or ROOT) / "reports"

# --- Market data ---------------------------------------------------------------

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

HISTORY_START = "2019-01-01"          # backtests start here (or at a coin's listing)
TIMEFRAMES = ["1h", "4h", "1d"]
TF_HOURS = {"1h": 1, "4h": 4, "1d": 24}

UNIVERSE_SIZE = 30                    # most-traded USDT pairs by average daily quote volume...
UNIVERSE_VOLUME_DAYS = 30             # ...over this many days, so one day's spike can't buy a place
UNIVERSE_PREFILTER = 80               # candidates taken from today's ranking before averaging
UNIVERSE_MIN_HISTORY_DAYS = 180       # coins listed more recently than this are left out
STABLECOIN_BAND = (0.97, 1.03)        # every recent daily close inside this band = a stablecoin
QUOTE = "USDT"
EXCLUDED_BASES = {
    # stablecoins and fiat
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD", "USDE", "USD1", "RLUSD", "PYUSD",
    "EUR", "GBP", "TRY", "BRL", "AEUR", "EURI", "XUSD", "USDS", "BFUSD",
    # wrapped or pegged assets that just track something else
    "WBTC", "WBETH", "BETH", "PAXG", "XAUT", "STETH",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

REQUEST_PAUSE_S = 0.12                # polite gap between API calls
MAX_USED_WEIGHT = 4800                # back off when Binance reports more than this per minute

# --- Costs ---------------------------------------------------------------------

# Round trip (buy + sell): taker fees plus a slippage allowance.
COST_MAJORS = 0.0025
COST_OTHERS = 0.0040
MAJORS = {"BTCUSDT", "ETHUSDT"}

# --- Signals -------------------------------------------------------------------

TREND_MA_WINDOWS = [20, 50]                       # close crosses above this moving average
DONCHIAN_LOOKBACKS = [10, 20, 55, 100]            # close above the prior N-candle high
TS_MOMENTUM_WEEKS = [1, 2, 4]                     # own return over this many weeks...
TS_MOMENTUM_TOP_QUANTILE = 0.80                   # ...in the top fifth of its past year
TS_MOMENTUM_HISTORY_DAYS = 365
XS_MOMENTUM_WEEKS = [2, 3]                        # rank coins by return over this many weeks
XS_MOMENTUM_TOP_FRACTION = 0.20                   # top fifth of the universe gets a signal
XS_MOMENTUM_MIN_COINS = 8                         # skip a week with fewer coins trading

# Intraday experiments (1h candles only)
FADE_HOURS = [1, 2, 4]                            # size of the move being faded
FADE_SIGMA = 2.5                                  # a drop bigger than this many standard deviations
FADE_VOL_DAYS = 30                                # standard deviation measured over this window
INTRADAY_MOM_TOP_QUANTILE = 0.80                  # first hour of the UTC day in its top fifth
INTRADAY_MOM_HISTORY_DAYS = 90

# --- Exits and scoring ---------------------------------------------------------

ATR_WINDOW = 14
TARGET_ATR = 2.0
STOP_ATR = 1.0
TIME_LIMIT_BARS = {"1h": 24, "4h": 42, "1d": 7}   # give up after this many candles

# Fixed-horizon checks, in candles of the signal's own timeframe.
HORIZON_BARS = {
    "1h": [4, 12, 24],
    "4h": [6, 18, 42],          # 1, 3 and 7 days
    "1d": [3, 7, 14, 30],
}

RANDOM_DRAWS_PER_TRADE = 20
RANDOM_WINDOW_DAYS = 90                           # random entries come from +/- this many days
REGIME_MA_DAYS = 200                              # BTC above or below its 200-day average
RANDOM_SEED = 7

# Variants declared after looking at a backtest. History can't promote them: their backtest
# is shown for reference, but only live paper trades can give them a verdict.
FORWARD_ONLY_VARIANTS = {"fade1h_hold24_1h"}
FORWARD_ONLY_VERDICT = "Judged on live trades only"

EDGE_T = 3.0                                      # t-statistic needed to call something an edge
LOSING_T = -2.0
ALPHA = 0.05                                      # after Holm correction across every variant
VERDICT_TIERS = [(30, "No verdict"), (100, "Early read"), (300, "Provisional")]  # below n -> label
VERDICT_TOP = "Meaningful"
BOOTSTRAP_RESAMPLES = 2000

# --- Live engine (Phase 2) -------------------------------------------------------

SERVER_HOST = "127.0.0.1"                         # reachable from the phone itself only
SERVER_PORT = 8765
LIVE_TICK_S = 30                                  # how often the engine wakes up
LIVE_HISTORY_DAYS = 420                           # candles loaded per check: a year of momentum history + margin

PRICE_WATCH_EVERY_S = 180
PRICE_WATCH_WINDOW_MIN = 20                       # "moved X% in the last 20 minutes"
PRICE_WATCH_MOVE = 0.05
PRICE_WATCH_MOVE_MAJORS = 0.03                    # BTC and ETH move less, so a smaller move counts
PRICE_WATCH_COOLDOWN_MIN = 60                     # one move alert per coin per hour at most

# Defaults for the Settings screen. 1h signals fire many times a day across 30 coins,
# so they are logged and scored but do not notify unless switched on.
SETTINGS_DEFAULTS = {
    "alerts_on": True,
    "speak_on": True,
    "alert_1h": False,
    "alert_4h": True,
    "alert_1d": True,
    "alert_moves": True,
    "night_dim": True,
    "check_updates": True,
}
IDLE_RETURN_S = 120                               # back to the chart and dimmed after this long untouched
PIXEL_SHIFT_S = 180                               # nudge the layout a few pixels against burn-in

# --- Updates ---------------------------------------------------------------------

GITHUB_REPO = "ikverse/Signal-Lab"
UPDATE_CHECK_HOURS = 24
SELF_TEST_TIMEOUT_S = 900                         # the Note 9 is slow; the test suite must still finish
