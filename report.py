"""Turns scores into the printed scorecard and a saved Markdown + JSON report."""

import datetime as dt
import json

import config


def _pct(x, digits=1, sign=False):
    if x is None:
        return "—"
    return f"{x * 100:+.{digits}f}" if sign else f"{x * 100:.{digits}f}"


def _num(x, digits=2):
    return "—" if x is None or x != x else f"{x:.{digits}f}"


def verdict_text(s):
    v = s.get("verdict", "No verdict")
    if v in ("No verdict", config.FORWARD_ONLY_VERDICT):
        return v
    return f"{v} · {s['details']['tier'].lower()}"


def _date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%d %b %Y")


def period_of(conn, symbols, tfs, since_ms):
    q = ",".join("?" * len(symbols))
    tq = ",".join("?" * len(tfs))
    row = conn.execute(
        f"SELECT MIN(open_time), MAX(close_time) FROM candles WHERE symbol IN ({q}) "
        f"AND tf IN ({tq}) AND open_time>=?", (*symbols, *tfs, since_ms)).fetchone()
    return [_date(row[0]), _date(row[1])] if row and row[0] else ["?", "?"]


HEADER = ["Signal", "Trades", "Win %", "Random %", "Lift", "Avg net", "Excess", "t", "Holm p", "Verdict"]


def rows_for(scores, tf):
    out = []
    for s in sorted((s for s in scores if s["tf"] == tf), key=lambda s: (s["family"], s["variant"])):
        lift = (None if s["hit"] is None or s["random_hit"] is None
                else s["hit"] - s["random_hit"])
        out.append([
            s["variant"].rsplit("_", 1)[0], str(s["n"]), _pct(s["hit"]), _pct(s["random_hit"]),
            _pct(lift, sign=True), _pct(s["mean"], 2, True), _pct(s["excess"], 2, True),
            _num(s.get("t_cluster")), _num(s.get("p_holm"), 3), verdict_text(s),
        ])
    return out


def horizon_table(scores, tf):
    """Fixed holding periods: average excess over random per trade (%), with clustered t.
    These t-values are not corrected for multiple testing; treat them as clues, not verdicts."""
    picked = sorted((s for s in scores if s["tf"] == tf and s["n"]),
                    key=lambda s: (s["family"], s["variant"]))
    hs = sorted({h for s in picked for h in s["details"].get("horizons", {})}, key=int)
    header = ["Signal"] + [f"{h} candles" for h in hs]
    rows = []
    for s in picked:
        cells = [s["variant"].rsplit("_", 1)[0]]
        for h in hs:
            d = s["details"]["horizons"].get(h)
            cells.append("—" if not d else f"{d['excess'] * 100:+.2f} ({_num(d['t_cluster'], 1)})")
        rows.append(cells)
    return header, rows


def _fmt_rows(header, rows, left=(0,)):
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    fmt = lambda r: "  ".join(c.ljust(w) if i in left else c.rjust(w)
                              for i, (c, w) in enumerate(zip(r, widths)))
    return [fmt(header), fmt(["-" * w for w in widths])] + [fmt(r) for r in rows]


def render_text(scores, meta):
    lines = [
        "",
        f"Signal Lab scorecard · run {meta['run_id']} · {meta['period'][0]} – {meta['period'][1]}",
        f"{len(meta['symbols'])} coins · costs {config.COST_MAJORS:.2%} BTC/ETH, {config.COST_OTHERS:.2%} others · "
        f"exits {config.TARGET_ATR:g}x ATR target, {config.STOP_ATR:g}x ATR stop · "
        f"{meta['trials']} variants ever tried",
        "Win % and returns are after costs. Random = same coin, +/-90 days, same BTC regime, same exits.",
        f"Edge needs clustered t >= {config.EDGE_T:g} and Holm p < {config.ALPHA:g}.",
    ]
    for tf in config.TIMEFRAMES:
        rows = rows_for(scores, tf)
        if not rows:
            continue
        rp = meta["repaint"].get(tf, {})
        lines += ["", f"── {tf} ── repaint check: {rp.get('checks', 0)} comparisons, "
                      f"{len(rp.get('mismatches', []))} mismatches"]
        lines += _fmt_rows(HEADER, rows, left=(0, 9))
        hh, hr = horizon_table(scores, tf)
        if hr:
            lines += ["", f"{tf} fixed holding periods · excess over random per trade, % (t, uncorrected)"]
            lines += _fmt_rows(hh, hr)
    return "\n".join(lines)


def save(scores, meta):
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = config.REPORTS_DIR / f"scorecard_run{meta['run_id']}_{dt.date.today().isoformat()}"
    md = [
        f"# Scorecard, run {meta['run_id']}",
        "",
        f"Generated {meta['generated']} · data {meta['period'][0]} – {meta['period'][1]} · "
        f"{len(meta['symbols'])} coins · {meta['trials']} signal variants ever tried.",
        "",
        "**Read this first.** The coins are today's most-traded pairs, so coins that collapsed or were "
        "delisted are missing (survivorship bias): results here look better than reality. "
        "Forward paper trading is the real test.",
        "",
        f"- Costs per round trip: {config.COST_MAJORS:.2%} for BTC and ETH, {config.COST_OTHERS:.2%} for others.",
        f"- Exits: target {config.TARGET_ATR:g}x ATR, stop {config.STOP_ATR:g}x ATR, time limits "
        f"{config.TIME_LIMIT_BARS} candles. Stop assumed first when both are hit in one candle.",
        "- Random: same coin, within 90 days, same BTC regime (above or below its 200-day average), same exits.",
        f"- Edge: clustered t >= {config.EDGE_T:g} and Holm-corrected p < {config.ALPHA:g}. "
        "t is clustered by calendar week, so many coins signalling together count once.",
        "- Lift is win-rate points above random. Excess is average net return above random, per trade.",
    ]
    for tf in config.TIMEFRAMES:
        rows = rows_for(scores, tf)
        if not rows:
            continue
        rp = meta["repaint"].get(tf, {})
        md += ["", f"## {tf}", "",
               f"Repaint check: {rp.get('checks', 0)} comparisons, {len(rp.get('mismatches', []))} mismatches.",
               "", "| " + " | ".join(HEADER) + " |", "|" + "---|" * len(HEADER)]
        md += ["| " + " | ".join(r) + " |" for r in rows]
        hh, hr = horizon_table(scores, tf)
        if hr:
            md += ["", f"**{tf} fixed holding periods.** Average excess over random per trade, in %, "
                       "with clustered t in brackets. Not corrected for multiple testing.", "",
                   "| " + " | ".join(hh) + " |", "|" + "---|" * len(hh)]
            md += ["| " + " | ".join(r) + " |" for r in hr]
    stem.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps({"meta": meta, "scores": scores}, indent=1,
                                                    default=str), encoding="utf-8")
    return stem.with_suffix(".md")
