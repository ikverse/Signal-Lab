"""Download history, replay every signal, score it, print the scorecard.

    python backtest.py                    # download/update data, then score everything
    python backtest.py --skip-download    # score the data already stored
    python backtest.py --tf 1d            # one timeframe only

The repaint check recomputes all signals on history cut off at sample points and confirms
that nothing up to each cut changes. Any difference means a signal peeked at the future.
"""

import argparse
import datetime as dt
import sys

import numpy as np

import config
import data_binance
import report
import scorecard
import store
from signals_intraday import intraday_signals
from signals_trend import single_coin_signals, xs_momentum


def compute_signals(panel, tf):
    """{(variant, family, params): {symbol: bool array}} for every signal on this timeframe."""
    out = {}
    for sym, c in panel.items():
        per_coin = single_coin_signals(c, tf)
        per_coin.update(intraday_signals(c, tf))
        for key, flags in per_coin.items():
            out.setdefault(key, {})[sym] = flags
    out.update(xs_momentum(panel, tf))
    return out


def truncate(panel, cut_time):
    out = {}
    for sym, c in panel.items():
        k = np.searchsorted(c["t"], cut_time, side="right")
        if k > 0:
            out[sym] = {key: (v[:k] if isinstance(v, np.ndarray) else v) for key, v in c.items()}
    return out


def repaint_check(panel, tf, full, cuts, rng):
    """Recompute signals on history cut at `cuts` random times; every flag up to each cut
    must match the full-history run. Returns (checks_done, list of mismatches)."""
    times = np.unique(np.concatenate([c["t"] for c in panel.values()]))
    if len(times) < 10:
        return 0, []
    picks = rng.choice(times[len(times) // 10:], size=min(cuts, len(times)), replace=False)
    done, bad = 0, []
    for T in picks:
        part = compute_signals(truncate(panel, T), tf)
        for key, by_sym in part.items():
            for sym, flags in by_sym.items():
                done += 1
                if not np.array_equal(flags, full[key][sym][:len(flags)]):
                    bad.append(f"{key[0]} {sym} cut {dt.datetime.fromtimestamp(T / 1000, dt.timezone.utc):%Y-%m-%d %H:%M}")
    return done, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=config.HISTORY_START)
    ap.add_argument("--tf", nargs="+", default=config.TIMEFRAMES, choices=config.TIMEFRAMES)
    ap.add_argument("--symbols", nargs="+", help="override the top-30 universe")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--no-save-trades", action="store_true", help="score without writing every trade to the database")
    ap.add_argument("--replay-cuts", type=int, default=None, help="repaint-check cut points per timeframe")
    args = ap.parse_args(argv)
    # Windows consoles default to cp1252, which can't print the scorecard's dashes and dots
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = store.connect()
    if args.symbols:
        symbols = args.symbols
    elif args.skip_download and store.latest_universe(conn):
        symbols = store.latest_universe(conn)
    else:
        print("Picking the universe (top USDT pairs by 30-day average volume)...")
        symbols = data_binance.pick_universe(conn)
    if "BTCUSDT" not in symbols:
        symbols = ["BTCUSDT"] + symbols

    if not args.skip_download:
        print(f"Downloading {', '.join(args.tf)} candles and funding since {args.since} for {len(symbols)} coins...")
        tfs = sorted(set(args.tf) | {"1d"}, key=config.TIMEFRAMES.index)   # 1d always, for the BTC regime
        data_binance.download_all(conn, symbols, tfs, args.since)

    since_ms = data_binance.to_ms(args.since)
    btc_daily = store.load_candles(conn, "BTCUSDT", "1d", 0)
    if btc_daily is None:
        sys.exit("No BTC daily candles stored. Run without --skip-download first.")

    params = {"since": args.since, "timeframes": args.tf, "symbols": symbols,
              "costs": [config.COST_MAJORS, config.COST_OTHERS],
              "exits": [config.TARGET_ATR, config.STOP_ATR, config.TIME_LIMIT_BARS]}
    run_id = store.start_run(conn, params)
    rng = np.random.default_rng(config.RANDOM_SEED)
    check_rng = np.random.default_rng(config.RANDOM_SEED + 1)   # separate, so cut points never shift the baselines
    scores, repaint = [], {}

    for tf in args.tf:
        panel = {}
        for sym in symbols:
            c = store.load_candles(conn, sym, tf, since_ms)
            if c is not None and len(c["t"]) > 200:
                panel[sym] = c
        if not panel:
            print(f"{tf}: no data, skipped")
            continue
        regimes = {s: scorecard.regime_series(btc_daily, c["close_time"]) for s, c in panel.items()}
        print(f"\n{tf}: computing signals for {len(panel)} coins...", flush=True)
        signals = compute_signals(panel, tf)

        cuts = args.replay_cuts if args.replay_cuts is not None else {"1h": 3, "4h": 6, "1d": 20}[tf]
        done, bad = repaint_check(panel, tf, signals, cuts, check_rng)
        repaint[tf] = {"cuts": cuts, "checks": done, "mismatches": bad}
        print(f"{tf}: repaint check {done} comparisons, {len(bad)} mismatches", flush=True)

        for (name, family, frozen), flags in sorted(signals.items()):
            p = dict(frozen)
            store.register_variant(conn, run_id, name, family, tf, p)
            trades, rnets = scorecard.run_variant(flags, panel, tf, p, regimes, rng)
            s = scorecard.score(name, family, tf, trades, rnets, rng)
            scores.append(s)
            if not args.no_save_trades:
                store.insert_results(conn, run_id, name, tf, trades)
            print(f"  {name:<20} {s['n']:>6} trades", flush=True)

    trials = store.variants_ever_tried(conn)
    scorecard.correct_and_judge(scores, trials)
    for s in scores:
        store.insert_score(conn, run_id, s)

    meta = {"run_id": run_id, "since": args.since, "symbols": symbols, "trials": trials,
            "repaint": repaint, "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "period": report.period_of(conn, symbols, args.tf, since_ms)}
    print(report.render_text(scores, meta))
    path = report.save(scores, meta)
    print(f"\nSaved {path}")
    if any(r["mismatches"] for r in repaint.values()):
        print("WARNING: the repaint check found signals that change when more data arrives.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
