/* Signal Lab app: five screens behind a right-edge rail, all data from the local server.
   Routes live in the URL hash, so Android's back gesture walks back through them. */

const U = "#089981", D = "#f23645", M = "#787b86", G = "#1c1f26", T = "#d1d4dc", A = "#2962ff";
const TF_LABEL = { "1h": "1h", "4h": "4h", "1d": "1D" };
const FAMILY_DOC = { donchian: "donchian", trend_state: "trend_state", ts_momentum: "ts_momentum",
  xs_momentum: "xs_momentum", big_move_fade: "big_move_fade", intraday_momentum: "intraday_momentum" };
const MAIN = ["trend_state", "donchian", "ts_momentum", "xs_momentum"];
const EXPERIMENTS = ["big_move_fade", "intraday_momentum"];

const state = { status: null, watch: [], score: null, chart: null, chartKey: "", lastInput: Date.now(),
  idle: false, timers: [], docs: null };

// ---------- helpers ----------
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = (p, o) => fetch(p, o).then((r) => r.json());
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const short = (s) => (s || "").replace(/USDT$/, "");
const pct = (x, d = 2, sign = true) => (x == null ? "—" : `${sign && x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%`);
const cls = (x) => (x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "");
const num = (x, d = 2) => (x == null || Number.isNaN(x) ? "—" : Number(x).toFixed(d));
function price(p) {
  if (p == null) return "—";
  if (p >= 1000) return p.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (p >= 1) return p.toFixed(p >= 100 ? 2 : 3);
  return p.toPrecision(4);
}
function when(ms) {
  if (!ms) return "—";
  const d = new Date(ms);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " +
    d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
function label(variant) {
  const v = variant.replace(/_(1h|4h|1d)$/, "");
  let m;
  if ((m = v.match(/^donchian(\d+)$/))) return `Donchian ${m[1]}`;
  if ((m = v.match(/^trend_ma(\d+)$/))) return `Trend state ${m[1]}`;
  if ((m = v.match(/^tsmom(\d+)w$/))) return `TS momentum ${m[1]}w`;
  if ((m = v.match(/^xsmom(\d+)w$/))) return `XS momentum ${m[1]}w`;
  if ((m = v.match(/^fade(\d+)h_hold(\d+)$/))) return `Fade ${m[1]}h, hold ${m[2]}`;
  if ((m = v.match(/^fade(\d+)h$/))) return `Big-move fade ${m[1]}h`;
  if (v === "intraday_mom") return "Intraday momentum";
  return v;
}
const tfOf = (variant) => (variant.match(/_(1h|4h|1d)$/) || [])[1];
function clearTimers() { state.timers.forEach(clearInterval); state.timers = []; }
function every(ms, fn) { state.timers.push(setInterval(fn, ms)); }

// ---------- router ----------
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const name = parts[0] || "chart";
  document.querySelectorAll("#rail a").forEach((a) => a.classList.toggle("on", a.dataset.route === name));
  clearTimers();
  if (state.chart) { klinecharts.dispose("kc"); state.chart = null; state.chartKey = ""; }
  const screens = { chart: chartScreen, scorecard: scorecardScreen, learn: learnScreen, alerts: alertsScreen, settings: settingsScreen };
  (screens[name] || chartScreen)(parts.slice(1));
}
window.addEventListener("hashchange", route);

// ---------- chart screen ----------
const CHART_STYLES = {
  grid: { horizontal: { color: "#111318" }, vertical: { color: "#111318" } },
  candle: {
    bar: { upColor: U, downColor: D, noChangeColor: M, upBorderColor: U, downBorderColor: D, noChangeBorderColor: M,
      upWickColor: U, downWickColor: D, noChangeWickColor: M },
    priceMark: { high: { show: false }, low: { show: false },
      last: { upColor: U, downColor: D, line: { show: false }, text: { family: "Roboto", size: 11 } } },
    tooltip: { showRule: "none" },
  },
  indicator: { tooltip: { showRule: "none" }, lastValueMark: { show: false },
    lines: [{ color: A, size: 1 }, { color: M, size: 1 }],
    bars: [{ upColor: "rgba(8,153,129,0.45)", downColor: "rgba(242,54,69,0.45)", noChangeColor: M }] },
  xAxis: { axisLine: { color: G }, tickLine: { color: G }, tickText: { color: M, size: 11, family: "Roboto" } },
  yAxis: { axisLine: { color: G }, tickLine: { color: G }, tickText: { color: M, size: 11, family: "Roboto" } },
  separator: { color: G },
  crosshair: { show: false, horizontal: { line: { color: "#3a3f4b" }, text: { family: "Roboto" } },
    vertical: { line: { color: "#3a3f4b" }, text: { family: "Roboto" } } },
};
const TXT = { size: 11, family: "Roboto", backgroundColor: "rgba(0,0,0,0)", borderSize: 0,
  paddingLeft: 0, paddingRight: 0, paddingTop: 0, paddingBottom: 0 };

function registerOverlays() {
  klinecharts.registerOverlay({
    name: "sigMark", totalStep: 2, needDefaultPointFigure: false, needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
    createPointFigures: ({ overlay, coordinates }) => {
      const p = coordinates[0], e = overlay.extendData || {}, c = e.color || T;
      const figs = [{ type: "polygon", attrs: { coordinates: [{ x: p.x, y: p.y + 5 }, { x: p.x - 4.5, y: p.y + 13 }, { x: p.x + 4.5, y: p.y + 13 }] },
        styles: { style: "fill", color: c } }];
      if (e.text) figs.push({ type: "text", ignoreEvent: true, attrs: { x: p.x, y: p.y + 16, text: e.text, align: "center", baseline: "top" }, styles: { ...TXT, color: c } });
      return figs;
    },
  });
  klinecharts.registerOverlay({
    name: "levels", totalStep: 2, needDefaultPointFigure: false, needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
    createPointFigures: ({ overlay, coordinates, bounding, yAxis }) => {
      const x = coordinates[0].x, e = overlay.extendData, figs = [];
      for (const [v, txt, color, dash] of [[e.target, "target", U, true], [e.entry, "entry", T, false], [e.stop, "stop", D, true]]) {
        if (v == null) continue;
        const y = yAxis.convertToPixel(v);
        figs.push({ type: "line", attrs: { coordinates: [{ x, y }, { x: bounding.width, y }] },
          styles: { style: dash ? "dashed" : "solid", color, dashedValue: [4, 3], size: 1 } });
        figs.push({ type: "text", ignoreEvent: true, attrs: { x: bounding.width - 4, y: y - 7, text: `${txt} ${price(v)}`, align: "right", baseline: "middle" }, styles: { ...TXT, color } });
      }
      return figs;
    },
  });
  klinecharts.registerOverlay({
    name: "exitMark", totalStep: 2, needDefaultPointFigure: false, needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
    createPointFigures: ({ overlay, coordinates }) => {
      const p = coordinates[0], e = overlay.extendData;
      return [{ type: "circle", attrs: { x: p.x, y: p.y, r: 3 }, styles: { style: "fill", color: e.color } },
        { type: "text", ignoreEvent: true, attrs: { x: p.x + 6, y: p.y, text: e.text, align: "left", baseline: "middle" }, styles: { ...TXT, color: e.color } }];
    },
  });
}

function makeChart(el, withVolume = true) {
  const chart = klinecharts.init(el, { styles: CHART_STYLES });
  chart.createIndicator({ name: "MA", calcParams: [20] }, false, { id: "candle_pane" });
  if (withVolume) chart.createIndicator({ name: "VOL", calcParams: [] }, false, { height: 54 });
  [60, 300, 900].forEach((ms) => setTimeout(() => chart.resize(), ms));
  return chart;
}
const toData = (rows) => rows.map((r) => ({ timestamp: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }));

async function chartScreen([symParam, tfParam]) {
  const sym = symParam || localStorage.getItem("sym") || "BTCUSDT";
  const tf = tfParam || localStorage.getItem("tf") || "1d";
  try { localStorage.setItem("sym", sym); localStorage.setItem("tf", tf); } catch (e) {}
  $("#screen").innerHTML = `
    <div class="bar">
      <span class="title">${esc(sym)}</span><span class="muted">Binance · ${TF_LABEL[tf]}</span>
      <span class="tfs">${["1h", "4h", "1d"].map((t) => `<button data-tf="${t}" class="${t === tf ? "on" : ""}">${TF_LABEL[t]}</button>`).join("")}</span>
      <span class="right"><span class="muted" id="live-price"></span>
        <a class="muted" target="_blank" rel="noopener" href="https://www.tradingview.com/chart/?symbol=BINANCE:${esc(sym)}">Open in TradingView <i class="ph ph-arrow-square-out"></i></a></span>
    </div>
    <div class="body split-r">
      <div class="chart-wrap">
        <div class="tools">
          <button data-tool="crosshair" title="Crosshair"><i class="ph ph-crosshair"></i></button>
          <button data-tool="segment" title="Trend line"><i class="ph ph-line-segment"></i></button>
          <button data-tool="horizontalStraightLine" title="Horizontal line"><i class="ph ph-minus"></i></button>
          <button data-tool="clear" title="Clear drawings"><i class="ph ph-trash"></i></button>
        </div>
        <div id="kc"></div>
      </div>
      <div class="pane side" id="side"></div>
    </div>`;
  document.querySelectorAll(".tfs button").forEach((b) => (b.onclick = () => (location.hash = `#/chart/${sym}/${b.dataset.tf}`)));
  wireTools();
  state.chart = makeChart($("#kc"));
  await loadChart(sym, tf);
  renderSide(sym, tf);
  every(60_000, () => renderSide(sym, tf));
  every(30_000, async () => {
    const key = JSON.stringify(state.status?.engine?.processed?.[tf] ?? null);
    if (key !== state.chartKey) await loadChart(sym, tf);
  });
}

function wireTools() {
  document.querySelectorAll(".tools button").forEach((b) => (b.onclick = () => {
    const tool = b.dataset.tool, chart = state.chart;
    if (!chart) return;
    if (tool === "crosshair") {
      b.classList.toggle("on");
      chart.setStyles({ crosshair: { show: b.classList.contains("on") } });
    } else if (tool === "clear") {
      chart.removeOverlay({ groupId: "user" });
    } else {
      chart.createOverlay({ name: tool, groupId: "user", styles: { line: { color: A } } });
    }
  }));
}

async function loadChart(sym, tf) {
  const [rows, ov] = await Promise.all([api(`/api/candles?symbol=${sym}&tf=${tf}&limit=600`), api(`/api/overlays?symbol=${sym}&tf=${tf}`)]);
  const chart = state.chart;
  if (!chart) return;
  state.chartKey = JSON.stringify(state.status?.engine?.processed?.[tf] ?? null);
  const data = toData(rows);
  chart.applyNewData(data);
  chart.setOffsetRightDistance(110);
  chart.removeOverlay({ groupId: "signals" });
  const lowAt = new Map(data.map((d) => [d.timestamp, d.low]));
  const closeAt = new Map(data.map((d) => [d.timestamp, d.close]));
  const tfMs = { "1h": 3600e3, "4h": 14400e3, "1d": 86400e3 }[tf];
  for (const t of ov.backtest || []) {      // past signals, faint
    const bar = t.entry_time - tfMs;
    if (lowAt.has(bar)) chart.createOverlay({ name: "sigMark", groupId: "signals", lock: true, points: [{ timestamp: bar, value: lowAt.get(bar) }], extendData: { color: "#3a3f4b" } });
  }
  for (const t of ov.live || []) {
    if (lowAt.has(t.bar_time)) chart.createOverlay({ name: "sigMark", groupId: "signals", lock: true,
      points: [{ timestamp: t.bar_time, value: lowAt.get(t.bar_time) }], extendData: { color: T, text: label(t.variant) } });
    if (t.exit_time == null) {
      chart.createOverlay({ name: "levels", groupId: "signals", lock: true, points: [{ timestamp: t.entry_time, value: t.entry_price }],
        extendData: { entry: t.entry_price, target: t.target, stop: t.stop } });
    } else {
      const bar = t.exit_time - tfMs + 1;
      if (closeAt.has(bar)) chart.createOverlay({ name: "exitMark", groupId: "signals", lock: true, points: [{ timestamp: bar, value: t.exit_price }],
        extendData: { color: t.net > 0 ? U : D, text: pct(t.net, 1) } });
    }
  }
}

async function renderSide(sym, tf) {
  const [watch, signals] = await Promise.all([api("/api/watchlist"), api("/api/signals?limit=14")]);
  state.watch = watch;
  const me = watch.find((w) => w.symbol === sym);
  if (me && $("#live-price")) $("#live-price").innerHTML = `<span class="bright">${price(me.price)}</span> <span class="${cls(me.change_24h)}">${pct(me.change_24h)}</span>`;
  const side = $("#side");
  if (!side) return;
  side.innerHTML = `
    <table class="rows"><tr><th>Symbol</th><th>Last</th><th>Chg%</th></tr>
      ${watch.map((w) => `<tr class="click ${w.symbol === sym ? "sel" : ""}" data-sym="${w.symbol}">
        <td>${short(w.symbol)}${w.active.length ? ` <span class="accent" style="font-size:11px">${w.active.map((t) => TF_LABEL[t]).join(" ")}</span>` : ""}</td>
        <td>${price(w.price)}</td><td class="${cls(w.change_24h)}">${pct(w.change_24h)}</td></tr>`).join("")}
    </table>
    <div class="section"><div class="label" style="padding-top:0">Latest signals</div>
      ${signals.length ? signals.map((t) => `<div class="list-item" data-sym="${t.symbol}" data-tf="${t.tf}">
          <span>${short(t.symbol)} <span class="muted">· ${label(t.variant)} · ${TF_LABEL[t.tf]}</span></span>
          <span class="${t.exit_time ? cls(t.net) : "muted"}">${t.exit_time ? pct(t.net, 1) : "open"}</span></div>`).join("")
        : `<div class="note">No live signals yet. The engine checks every candle close; the first ones will appear here.</div>`}
    </div>`;
  side.querySelectorAll("tr[data-sym]").forEach((r) => (r.onclick = () => (location.hash = `#/chart/${r.dataset.sym}/${tf}`)));
  side.querySelectorAll(".list-item").forEach((r) => (r.onclick = () => (location.hash = `#/chart/${r.dataset.sym}/${r.dataset.tf}`)));
}

// ---------- scorecard screen ----------
async function scorecardScreen([tabParam, tfParam, variantParam]) {
  const tab = tabParam || "signals", tf = tfParam || "1d";
  $("#screen").innerHTML = `
    <div class="bar"><span class="title">Scorecard</span>
      <span class="tabs">${[["signals", "Signals"], ["periods", "Holding periods"], ["live", "Live trades"]].map(([k, n]) =>
        `<button data-tab="${k}" class="${k === tab ? "on" : ""}">${n}</button>`).join("")}</span>
      ${tab !== "live" ? `<span class="tfs">${["1h", "4h", "1d"].map((t) => `<button data-tf="${t}" class="${t === tf ? "on" : ""}">${TF_LABEL[t]}</button>`).join("")}</span>` : ""}
      <span class="right muted" id="sc-meta"></span></div>
    <div class="body" id="sc-body"></div>`;
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => (location.hash = `#/scorecard/${b.dataset.tab}/${tf}`)));
  document.querySelectorAll(".tfs button").forEach((b) => (b.onclick = () => (location.hash = `#/scorecard/${tab}/${b.dataset.tf}`)));
  const sc = (state.score = await api("/api/scorecard"));
  $("#sc-meta").textContent = sc.run_id ? `Backtest run ${sc.run_id} · after fees · vs random entries` : "";
  if (!sc.run_id && tab !== "live") {
    $("#sc-body").innerHTML = `<div class="empty">No backtest has been scored yet. Run <code>python backtest.py</code> on the PC.</div>`;
    return;
  }
  if (tab === "signals") return scoreSignals(sc, tf, variantParam);
  if (tab === "periods") return scorePeriods(sc, tf);
  return scoreLive(sc);
}

function verdictShort(s) {
  return s.verdict.startsWith("Judged") ? "Live only" : s.verdict;
}
function lift(s) {
  if (s.hit == null || s.random_hit == null) return "—";
  const v = Math.round((s.hit - s.random_hit) * 1000) / 10;
  return (v > 0 ? "+" : "") + (v === 0 ? "0.0" : v.toFixed(1));
}

function verdictText(s) {
  if (s.verdict === "No verdict" || s.verdict.startsWith("Judged")) return s.verdict;
  return `${s.verdict} · ${(s.details.tier || "").toLowerCase()}`;
}

function scoreSignals(sc, tf, variantParam) {
  const rows = sc.scores.filter((s) => s.tf === tf).sort((a, b) => a.family.localeCompare(b.family) || a.variant.localeCompare(b.variant));
  const sel = rows.find((s) => s.variant === variantParam) || rows[0];
  $("#sc-body").className = "body split-r";
  $("#sc-body").innerHTML = `
    <div class="pane"><table class="rows">
      <tr><th>Signal</th><th>Trades</th><th>Win %</th><th>Random %</th><th>Lift</th><th>Avg net</th><th>Excess</th><th>t</th><th class="l">Verdict</th></tr>
      ${rows.map((s) => `<tr class="click ${s === sel ? "sel" : ""}" data-v="${s.variant}">
        <td>${label(s.variant)}</td><td>${s.n}</td><td>${num(s.hit * 100, 1)}</td><td class="muted">${num(s.random_hit * 100, 1)}</td>
        <td class="${cls(s.hit - s.random_hit)}">${lift(s)}</td>
        <td class="${cls(s.mean)}">${pct(s.mean)}</td><td class="${cls(s.excess)}">${pct(s.excess)}</td><td>${num(s.t_cluster)}</td>
        <td class="l ${s.verdict === "Losing" ? "down" : s.verdict === "Edge" ? "up" : "muted"}">${verdictShort(s)}</td></tr>`).join("")}
    </table>
    <div class="note">Win % and returns are after fees (0.25% BTC and ETH, 0.40% others). Random = same coin, same 90 days,
      same market regime, same exits. An edge needs t of 3 or more after correcting for every variant ever tried.</div></div>
    <div class="pane side" id="sc-detail"></div>`;
  document.querySelectorAll("tr[data-v]").forEach((r) => (r.onclick = () => (location.hash = `#/scorecard/signals/${tf}/${r.dataset.v}`)));
  if (!sel) return;
  const d = sel.details, live = sc.live.variants[sel.variant];
  const reg = d.by_regime || {};
  $("#sc-detail").innerHTML = `
    <div class="label bright" style="font-size:13px">${label(sel.variant)} <span class="muted">· ${TF_LABEL[tf]}</span></div>
    <div class="kv"><span class="muted">Verdict</span><span>${esc(verdictText(sel))}</span></div>
    <div class="kv"><span class="muted">Trades</span><span>${sel.n}</span></div>
    <div class="kv"><span class="muted">Targets hit</span><span>${d.exits?.target ?? "—"}</span></div>
    <div class="kv"><span class="muted">Stopped out</span><span>${d.exits?.stop ?? "—"}</span></div>
    <div class="kv"><span class="muted">Time exits</span><span>${d.exits?.time ?? "—"}</span></div>
    <div class="kv"><span class="muted">Avg candles held</span><span>${num(d.avg_bars_held, 1)}</span></div>
    <div class="kv"><span class="muted">Profit factor</span><span>${num(sel.profit_factor)}</span></div>
    <div class="section">
      <div class="kv"><span class="muted">Excess, BTC uptrend</span><span class="${cls(reg.btc_above_200d?.mean_excess)}">${pct(reg.btc_above_200d?.mean_excess)}</span></div>
      <div class="kv"><span class="muted">Excess, BTC downtrend</span><span class="${cls(reg.btc_below_200d?.mean_excess)}">${pct(reg.btc_below_200d?.mean_excess)}</span></div>
    </div>
    <div class="section"><div class="label" style="padding-top:0">Live paper trades</div>
      ${live ? `<div class="kv"><span class="muted">Closed</span><span>${live.n}</span></div>
        <div class="kv"><span class="muted">Win %</span><span>${num(live.hit * 100, 1)}</span></div>
        <div class="kv"><span class="muted">Avg net</span><span class="${cls(live.mean)}">${pct(live.mean)}</span></div>
        <div class="kv"><span class="muted">Excess vs random</span><span class="${cls(live.mean_excess)}">${pct(live.mean_excess)}</span></div>`
        : `<div class="note" style="padding-top:2px">None closed yet.</div>`}
    </div>
    <div class="actions"><a class="link-btn" href="#/learn/signals/${FAMILY_DOC[sel.family] || ""}">How it works</a></div>`;
}

function scorePeriods(sc, tf) {
  const rows = sc.scores.filter((s) => s.tf === tf && s.n).sort((a, b) => a.family.localeCompare(b.family) || a.variant.localeCompare(b.variant));
  const hs = [...new Set(rows.flatMap((s) => Object.keys(s.details.horizons || {})))].sort((a, b) => a - b);
  $("#sc-body").className = "body";
  $("#sc-body").innerHTML = `<div class="pane"><table class="rows">
      <tr><th>Signal</th>${hs.map((h) => `<th>${h} candles</th>`).join("")}</tr>
      ${rows.map((s) => `<tr><td>${label(s.variant)}</td>${hs.map((h) => {
        const x = s.details.horizons?.[h];
        return x ? `<td><span class="${cls(x.excess)}">${pct(x.excess)}</span> <span class="muted">(${num(x.t_cluster, 1)})</span></td>` : "<td class='muted'>—</td>";
      }).join("")}</tr>`).join("")}
    </table>
    <div class="note">Average return above random entries held for the same time, after fees, with t in brackets.
      These are not corrected for testing many variants: treat them as clues, not verdicts.</div></div>`;
}

function scoreLive(sc) {
  $("#sc-body").className = "body split-r";
  $("#sc-body").innerHTML = `<div class="pane" id="lv-trades"></div><div class="pane side" id="lv-side"></div>`;
  api("/api/trades?limit=300").then((trades) => {
    $("#lv-trades").innerHTML = trades.length ? `<table class="rows">
      <tr><th>Opened</th><th class="l">Coin</th><th class="l">Signal</th><th>TF</th><th>Entry</th><th>Exit</th><th>Net</th><th>Excess</th></tr>
      ${trades.map((t) => `<tr class="click" data-sym="${t.symbol}" data-tf="${t.tf}"><td>${when(t.detected_at)}</td><td class="l">${short(t.symbol)}</td>
        <td class="l">${label(t.variant)}</td><td>${TF_LABEL[t.tf]}</td><td>${price(t.entry_price)}</td>
        <td>${t.exit_time ? `${price(t.exit_price)} <span class="muted">${t.exit_reason}</span>` : "<span class='muted'>open</span>"}</td>
        <td class="${cls(t.net)}">${t.exit_time ? pct(t.net) : ""}</td><td class="${cls(t.excess)}">${t.excess != null ? pct(t.excess) : ""}</td></tr>`).join("")}
      </table>` : `<div class="empty">No live paper trades yet. Every signal the engine sees from now on is logged here, opened at the next candle's open and closed at its target, stop or time limit.</div>`;
    document.querySelectorAll("#lv-trades tr[data-sym]").forEach((r) => (r.onclick = () => (location.hash = `#/chart/${r.dataset.sym}/${r.dataset.tf}`)));
  });
  const live = sc.live, eq = live.equity, total = eq.length ? eq[eq.length - 1][1] : 0;
  $("#lv-side").innerHTML = `
    <div class="label bright" style="font-size:13px">Paper account</div>
    ${eq.length > 1 ? equitySvg(eq) : `<div class="note">The line appears after the first trades close.</div>`}
    <div class="kv"><span class="muted">Closed trades</span><span>${live.closed}</span></div>
    <div class="kv"><span class="muted">Open now</span><span>${live.open}</span></div>
    <div class="kv"><span class="muted">Sum of returns</span><span class="${cls(total)}">${pct(total, 1)}</span></div>
    <div class="note">Live random entries come from the past 90 days only, because a live trade can't look ahead.</div>`;
}

function equitySvg(eq) {
  const W = 200, H = 90, xs = eq.map((p) => p[0]), ys = eq.map((p) => p[1]).concat([0]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys), hi = Math.max(...ys);
  const X = (x) => 4 + ((x - x0) / Math.max(1, x1 - x0)) * (W - 8), Y = (y) => 6 + ((hi - y) / Math.max(1e-9, hi - lo)) * (H - 12);
  const last = eq[eq.length - 1][1];
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;padding:0 8px">
    <line x1="0" x2="${W}" y1="${Y(0)}" y2="${Y(0)}" stroke="${G}"/>
    <polyline fill="none" stroke="${last >= 0 ? U : D}" stroke-width="1.4" points="${eq.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ")}"/></svg>`;
}

// ---------- learn screen ----------
async function learnScreen([group, name]) {
  state.docs = state.docs || (await api("/api/docs"));
  const docs = state.docs;
  group = group || "signals"; name = name || "donchian";
  const byName = Object.fromEntries(docs.map((d) => [`${d.group}/${d.name}`, d]));
  const item = (g, n) => byName[`${g}/${n}`] ? `<div class="list-item ${g === group && n === name ? "sel" : ""}" data-doc="${g}/${n}">${esc(byName[`${g}/${n}`].title)}</div>` : "";
  $("#screen").innerHTML = `
    <div class="bar"><span class="title">Learn</span><span class="right muted">Settings and numbers shown are read live from the engine</span></div>
    <div class="body split-l">
      <div class="pane side-l">
        <div class="group">Main signals</div>${MAIN.map((n) => item("signals", n)).join("")}
        <div class="group">Experiments</div>${EXPERIMENTS.map((n) => item("signals", n)).join("")}
        <div class="group">Basics</div>${docs.filter((d) => d.group === "basics").map((d) => item("basics", d.name)).join("")}
      </div>
      <div class="pane"><div class="doc" id="doc"></div></div>
    </div>`;
  document.querySelectorAll("[data-doc]").forEach((el) => (el.onclick = () => (location.hash = `#/learn/${el.dataset.doc}`)));
  const { markdown } = await api(`/api/docs/${group}/${name}`);
  const doc = $("#doc");
  doc.innerHTML = marked.parse(markdown || "");
  doc.querySelectorAll("pre code.language-mermaid").forEach((code) => {
    const div = document.createElement("div");
    div.className = "mermaid";
    div.textContent = code.textContent;
    code.parentElement.replaceWith(div);
  });
  try { await mermaid.run({ nodes: doc.querySelectorAll(".mermaid") }); } catch (e) { console.warn(e); }
  for (const el of doc.querySelectorAll(".doc-live")) {
    if (el.dataset.kind === "scorecard") fillDocScore(el, el.dataset.family);
    else fillDocExamples(el, el.dataset.family);
  }
}

async function fillDocScore(el, family) {
  const sc = state.score || (state.score = await api("/api/scorecard"));
  const rows = sc.scores.filter((s) => s.family === family).sort((a, b) => a.tf.localeCompare(b.tf) || a.variant.localeCompare(b.variant));
  if (!rows.length) { el.innerHTML = `<p class="muted">Not scored yet.</p>`; return; }
  el.innerHTML = `<table><tr><th>Variant</th><th>TF</th><th>Trades</th><th>Win vs random</th><th>Excess</th><th>Verdict</th><th>Live</th></tr>
    ${rows.map((s) => { const lv = sc.live.variants[s.variant];
      return `<tr><td><a href="#/scorecard/signals/${s.tf}/${s.variant}">${label(s.variant)}</a></td><td>${TF_LABEL[s.tf]}</td><td>${s.n}</td>
      <td>${num(s.hit * 100, 1)}% vs ${num(s.random_hit * 100, 1)}%</td><td class="${cls(s.excess)}">${pct(s.excess)}</td>
      <td>${esc(verdictText(s))}</td><td class="muted">${lv ? `${lv.n} closed, ${pct(lv.mean_excess)}` : "none yet"}</td></tr>`; }).join("")}</table>`;
}

async function fillDocExamples(el, family) {
  const ex = await api(`/api/examples?family=${family}`);
  const picks = [["win", "Worked"], ["loss", "Failed"]].filter(([k]) => ex[k]);
  if (!picks.length) { el.innerHTML = `<p class="muted">No examples yet.</p>`; return; }
  el.innerHTML = `<div class="examples">${picks.map(([k, title]) => `<div><div class="ex-chart" id="ex-${k}"></div>
    <p class="muted" style="margin:4px 0 0;font-size:12px">${title} · ${short(ex[k].symbol)} · ${new Date(ex[k].entry_time).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} · ${ex[k].exit_reason} after ${ex[k].bars_held} candles ·
    <span class="${cls(ex[k].net)}">${pct(ex[k].net, 1)}</span> after fees</p></div>`).join("")}</div>`;
  for (const [k] of picks) {
    const t = ex[k], tfMs = { "1h": 3600e3, "4h": 14400e3, "1d": 86400e3 }[t.tf];
    const rows = await api(`/api/candles?symbol=${t.symbol}&tf=${t.tf}&limit=60&end=${t.exit_time + 3 * tfMs}`);
    const chart = makeChart(document.getElementById(`ex-${k}`), false);
    chart.setStyles({ yAxis: { tickText: { size: 10 } } });
    const data = toData(rows);
    chart.applyNewData(data);
    chart.setOffsetRightDistance(60);
    const sig = data.find((d) => d.timestamp === t.entry_time - tfMs);
    if (sig) chart.createOverlay({ name: "sigMark", lock: true, points: [{ timestamp: sig.timestamp, value: sig.low }], extendData: { color: T } });
    chart.createOverlay({ name: "levels", lock: true, points: [{ timestamp: t.entry_time, value: t.entry_price }], extendData: { entry: t.entry_price } });
    const exitBar = t.exit_time - tfMs + 1;
    chart.createOverlay({ name: "exitMark", lock: true, points: [{ timestamp: exitBar, value: t.exit_price }], extendData: { color: t.net > 0 ? U : D, text: pct(t.net, 1) } });
  }
}

// ---------- alerts screen ----------
async function alertsScreen() {
  const list = await api("/api/alerts");
  if (list.length) try { localStorage.setItem("seenAlert", String(list[0].id)); } catch (e) {}
  $("#alert-badge").classList.remove("show");
  $("#screen").innerHTML = `<div class="bar"><span class="title">Alerts</span><span class="right muted">Everything the phone was told, newest first</span></div>
    <div class="body"><div class="pane">${list.length ? `<table class="rows">
      <tr><th>Time</th><th class="l">Alert</th><th class="l">Details</th></tr>
      ${list.map((a) => `<tr class="click" data-link="${esc(a.link || "")}"><td class="muted">${when(a.ts)}</td><td class="l">${esc(a.title)}</td><td class="l muted">${esc(a.body)}</td></tr>`).join("")}
    </table>` : `<div class="empty">No alerts yet. Daily and 4-hour signals, sudden price moves and updates will be listed here.</div>`}</div></div>`;
  document.querySelectorAll("tr[data-link]").forEach((r) => (r.onclick = () => r.dataset.link && (location.hash = r.dataset.link.replace(/^#?/, "#"))));
}

// ---------- settings screen ----------
const TOGGLES = [["alerts_on", "Notifications"], ["speak_on", "Spoken alerts"], ["alert_1d", "Daily signals"],
  ["alert_4h", "4-hour signals"], ["alert_1h", "Hourly signals (many a day)"], ["alert_moves", "Sudden price moves"],
  ["night_dim", "Dim more at night"], ["check_updates", "Check for updates daily"]];

async function settingsScreen() {
  const [s, st] = await Promise.all([api("/api/settings"), api("/api/status")]);
  state.status = st;
  $("#screen").innerHTML = `<div class="bar"><span class="title">Settings</span></div>
    <div class="body split-r" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
      <div class="pane">${TOGGLES.map(([k, n]) => `<div class="toggle ${s[k] ? "on" : ""}" data-k="${k}"><span>${n}</span><span class="switch"></span></div>`).join("")}
        <div class="section"><div class="label" style="padding-top:0">Engine</div>${engineRows(st)}</div></div>
      <div class="pane side" id="about"></div>
    </div>`;
  document.querySelectorAll(".toggle").forEach((t) => (t.onclick = async () => {
    const on = !t.classList.contains("on");
    t.classList.toggle("on", on);
    await post("/api/settings", { [t.dataset.k]: on });
  }));
  renderAbout();
}

function engineRows(st) {
  const e = st.engine;
  if (!e) return `<div class="note">The engine is off (server started with --no-engine).</div>`;
  const rows = [["Last check", when(e.last_tick)], ["Price watch", when(e.price_watch_at)],
    ...Object.entries(e.processed || {}).map(([tf, t]) => [`${TF_LABEL[tf]} candle processed`, when(t)])];
  return rows.map(([k, v]) => `<div class="kv"><span class="muted">${k}</span><span>${v}</span></div>`).join("") +
    (e.last_error ? `<pre class="out">Last problem (${esc(e.last_error.step)}, ${when(e.last_error.at)}): ${esc(e.last_error.error)}</pre>` : "");
}

async function renderAbout() {
  const u = await api("/api/update"), job = u.job || {};
  const el = $("#about");
  if (!el) return;
  el.innerHTML = `
    <div class="label bright" style="font-size:13px">Signal Lab ${esc(u.current)}</div>
    <div class="kv"><span class="muted">Latest release</span><span>${esc(u.latest || "—")}</span></div>
    <div class="kv"><span class="muted">Last checked</span><span>${when(u.checked_at)}</span></div>
    ${u.error ? `<div class="note">${esc(u.error)}</div>` : ""}
    <div class="actions">
      <button class="link-btn" data-a="check">Check now</button>
      ${u.available && !u.downloaded ? `<button class="link-btn" data-a="download">Download ${esc(u.latest)}</button>` : ""}
      ${u.available && u.downloaded ? `<button class="link-btn" data-a="install" ${u.installed_layout ? "" : "disabled"}>Install and restart</button>` : ""}
      ${u.previous ? `<button class="link-btn" data-a="rollback">Roll back to ${esc(u.previous)}</button>` : ""}
    </div>
    ${job.busy ? `<div class="note">Working: ${esc(job.busy)}…</div>` : ""}
    ${job.error ? `<pre class="out">${esc(job.error)}</pre>` : ""}
    ${job.done ? `<div class="note">${esc(job.done)}</div>` : ""}
    ${u.available && !u.installed_layout ? `<div class="note">Installing works on the phone. On the PC, update with git.</div>` : ""}
    ${u.available && u.notes ? `<div class="section"><div class="label" style="padding-top:0">What's new in ${esc(u.latest)}</div><div class="doc" style="padding:0 12px">${marked.parse(u.notes)}</div></div>` : ""}`;
  el.querySelectorAll("[data-a]").forEach((b) => (b.onclick = async () => {
    if (b.dataset.a === "install" && !confirm("Install the new version and restart Signal Lab?")) return;
    if (b.dataset.a === "rollback" && !confirm(`Go back to ${u.previous} and restart?`)) return;
    await post(`/api/update/${b.dataset.a}`);
    pollUpdate();
  }));
  if (job.busy) pollUpdate();
}

function pollUpdate() {
  const id = setInterval(async () => {
    const u = await api("/api/update").catch(() => null);
    if (!u) return;                       // server restarting
    if (!u.job.busy) { clearInterval(id); if (location.hash.startsWith("#/settings")) renderAbout(); }
  }, 1500);
}

// ---------- status, badges, screen care ----------
async function refreshStatus() {
  try {
    state.status = await api("/api/status");
    $("#update-badge").classList.toggle("show", !!state.status.update?.available);
    const alerts = await api("/api/alerts");
    let seen = 0;
    try { seen = Number(localStorage.getItem("seenAlert") || 0); } catch (e) {}
    $("#alert-badge").classList.toggle("show", alerts.length > 0 && alerts[0].id > seen && !location.hash.startsWith("#/alerts"));
  } catch (e) { /* server restarting; try again next time */ }
}

function onInput() {
  state.lastInput = Date.now();
  if (state.idle) { state.idle = false; document.body.classList.remove("idle", "night"); }
}
["pointerdown", "keydown", "wheel", "touchstart"].forEach((ev) => window.addEventListener(ev, onInput, { passive: true }));

setInterval(() => {
  const st = state.status, limit = (st?.idle_return_s || 120) * 1000;
  if (!state.idle && Date.now() - state.lastInput > limit) {
    state.idle = true;
    if (!location.hash.startsWith("#/chart") && location.hash !== "") location.hash = "#/chart";
    const h = new Date().getHours();
    document.body.classList.add("idle");
    document.body.classList.toggle("night", !!st?.settings?.night_dim && (h >= 22 || h < 7));
  }
}, 5000);

const SHIFTS = [[0, 0], [2, 1], [1, 2], [-1, 1], [-2, -1], [0, -2]];
let shiftIndex = 0;
function pixelShift() {
  shiftIndex = (shiftIndex + 1) % SHIFTS.length;
  const [x, y] = SHIFTS[shiftIndex];
  document.getElementById("shell").style.transform = `translate(${x}px, ${y}px)`;
}

window.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea")) return;
  const keys = { 1: "#/chart", 2: "#/scorecard", 3: "#/learn" };
  if (keys[e.key]) location.hash = keys[e.key];
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && location.hash.startsWith("#/chart") && state.watch.length) {
    const parts = location.hash.split("/"), sym = parts[2] || localStorage.getItem("sym"), tf = parts[3] || "1d";
    const i = state.watch.findIndex((w) => w.symbol === sym);
    const next = state.watch[(i + (e.key === "ArrowDown" ? 1 : -1) + state.watch.length) % state.watch.length];
    location.hash = `#/chart/${next.symbol}/${tf}`;
  }
});

// ---------- start ----------
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base",
  flowchart: { nodeSpacing: 14, rankSpacing: 22, padding: 6, wrappingWidth: 120, diagramPadding: 4 },
  themeVariables: { background: "#050505", primaryColor: "#050505", primaryBorderColor: "#3a3f4b", primaryTextColor: "#d1d4dc",
    secondaryColor: "#050505", tertiaryColor: "#050505", lineColor: "#5d606b", fontFamily: "Roboto", fontSize: "12px",
    edgeLabelBackground: "#050505" } });
registerOverlays();
refreshStatus().then(() => {
  route();
  setInterval(refreshStatus, 30_000);
  setInterval(pixelShift, (state.status?.pixel_shift_s || 180) * 1000);
});
