/* Metro Flood Response AI: AI pipeline explorer.
   One flat map + one tab per algorithm. The map shows only what the active algorithm decided;
   the right pane shows how it decided it, with the real numbers from this run. */
const { MapboxOverlay, PathLayer, ScatterplotLayer, TextLayer, LineLayer } = deck;

const STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json";
const HOME = { center: [55.235, 25.155], zoom: 10.25, pitch: 0, bearing: 0 };
const LINE_RGB = { Red: [220, 70, 70], Green: [52, 168, 83] };
const C = { cyan: [34, 211, 238], pink: [232, 121, 249], violet: [167, 139, 250], amber: [245, 158, 11], grey: [100, 116, 139], white: [241, 245, 249], blue: [56, 189, 248] };
const $ = (id) => document.getElementById(id);

let NET, SIM, RES = null, IDX = {};
const cmpRow = (metric, scenario) => (RES && RES.comparison ? RES.comparison.find((r) => r.scenario === scenario && r.metric === metric) : null);
const pmf = (m, s, d = 0) => (m == null ? "–" : `${Number(m).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })}${s == null ? "" : ` ± ${Number(s).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })}`}`);
let tab = "data", step = 0, stepF = 0, playing = false, sel = null;
let resPolicy = "ai", gaShow = "ga";
let SEARCH = null, searchK = 0, searchAnim = false, searchMode = "both";
const fuzzyCache = new Map();

/* ================================================================ helpers */
const fmt = (n, d = 0) => (n == null || Number.isNaN(n) ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const hhmm = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
const nm = (n) => { const s = NET.stations[IDX[n]]; return s ? s.display.replace(/ \((.*)\)$/, " ($1)") : n; };
const short = (n) => { const s = NET.stations[IDX[n]]; return s ? s.display.replace(/ \(.*\)$/, "").replace("Burj Khalifa/ Dubai Mall", "Burj Khalifa") : n; };
const isClosed = (i, t = step) => SIM.closed_at[i] >= 0 && SIM.closed_at[i] <= t;
const pos = (s) => [s.lon, s.lat];
function hav(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180, a = Math.sin(((lat2 - lat1) * r) / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 6371.0088 * 2 * Math.asin(Math.sqrt(a));
}
function ramp(t, stops) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < stops.length; i++) if (t <= stops[i][0]) {
    const [a, ca] = stops[i - 1], [b, cb] = stops[i], u = (t - a) / (b - a || 1);
    return [0, 1, 2].map((k) => Math.round(ca[k] + (cb[k] - ca[k]) * u));
  }
  return stops[stops.length - 1][1];
}
const prioRGB = (p) => ramp(p / 100, [[0, [34, 197, 94]], [0.35, [234, 179, 8]], [0.6, [249, 115, 22]], [0.85, [239, 68, 68]], [1, [239, 68, 68]]]);
const loadRGB = (r) => ramp(r / 2, [[0, [34, 197, 94]], [0.4, [234, 179, 8]], [0.5, [249, 115, 22]], [0.75, [239, 68, 68]], [1, [190, 18, 60]]]);
const waterRGB = (w) => ramp(w, [[0, [51, 65, 85]], [0.3, [14, 116, 144]], [0.7, [14, 165, 233]], [1, [186, 230, 253]]]);
const label = (p) => (p >= 80 ? "Critical" : p >= 55 ? "High" : p >= 30 ? "Medium" : "Low");
const css = (rgb, a = 1) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;
function stateAt(t) { let cur = null; for (const st of SIM.states) if (st.from_step <= t && (!cur || st.from_step >= cur.from_step)) cur = st; return cur; }
const finalState = () => [...SIM.states].reverse().find((s) => s.ga) || null;
const thr = () => NET.threshold_mm;

/* ================================================================ map */
const map = new maplibregl.Map({ container: "map", style: STYLE, ...HOME, attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false });
map.touchZoomRotate.disableRotation();
const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
map.addControl(overlay);

function tip(info, html) {
  const el = $("tooltip");
  if (!info.object) { el.style.display = "none"; return; }
  el.innerHTML = html(info.object);
  el.style.display = "block";
  const r = $("map").getBoundingClientRect();
  el.style.left = r.left + info.x + 14 + "px";
  el.style.top = r.top + info.y + 14 + "px";
}
const row = (k, v) => `<div class="row"><span>${k}</span><span>${v}</span></div>`;

function baseLayers(dim = false) {
  const a = dim ? 90 : 200;
  return [
    new PathLayer({ id: "track", data: NET.track_parts, getPath: (d) => d.path, getColor: (d) => [...LINE_RGB[d.line], a], getWidth: 2.2, widthUnits: "pixels", capRounded: true, jointRounded: true }),
  ];
}
function stationLayer(id, { color, radius, line, lineW = 1, pickable = true, tipHtml, data }) {
  return new ScatterplotLayer({
    id, data: data || NET.stations.map((s, i) => ({ s, i })), getPosition: (d) => pos(d.s), getRadius: radius, radiusUnits: "pixels",
    getFillColor: color, stroked: true, getLineColor: line || [10, 13, 18, 255], getLineWidth: lineW, lineWidthUnits: "pixels", pickable,
    onHover: (info) => tipHtml && tip(info, tipHtml), onClick: (info) => { if (info.object) { sel = info.object.s.name; refresh(); } },
    updateTriggers: { getFillColor: [step, tab, sel, resPolicy], getRadius: [step, tab, sel, resPolicy], getLineColor: [sel, step], getLineWidth: [sel] },
  });
}
const labelLayer = (id, items, color = [226, 232, 240], size = 11.5) => new TextLayer({
  id, data: items, getPosition: (d) => d.p, getText: (d) => d.t, getSize: size, getColor: d => d.c || color, getPixelOffset: (d) => d.o || [0, -14],
  fontFamily: "Inter, sans-serif", fontWeight: 600, outlineWidth: 3, outlineColor: [10, 13, 18, 255], fontSettings: { sdf: true }, characterSet: "auto",
});
const closedX = (t = step) => labelLayer("x", NET.stations.filter((s, i) => isClosed(i, t)).map((s) => ({ p: pos(s), t: "✕", o: [0, 0] })), [241, 245, 249], 13);

function legend(items) {
  $("mapLegend").innerHTML = items.map(([kind, color, text]) =>
    kind === "dot" ? `<div><span class="sw" style="background:${color}"></span>${text}</div>`
      : kind === "ring" ? `<div><span class="sw" style="border:2px solid ${color}"></span>${text}</div>`
      : kind === "line" ? `<div><span class="ln" style="background:${color}"></span>${text}</div>`
      : `<div><span class="ramp" style="background:linear-gradient(90deg,${color})"></span>${text}</div>`).join("");
}
const note = (html) => ($("mapNote").innerHTML = html ? `<span>${html}</span>` : "");

/* ================================================================ tab: DATA */
function dataLayers() {
  const four = new Set(NET.closures_2024);
  const maxD = Math.max(...NET.stations.map((s) => s.daily_trips));
  legend([["ramp", "#22c55e,#eab308,#ef4444", "April 2024 ridership drop (vs network)"], ["ring", "#fff", "Closed in April 2024"], ["dot", "#94a3b8", "Size = typical daily trips (2025)"]]);
  note("Real RTA data. Click a station for its numbers.");
  return [...baseLayers(),
    stationLayer("st", {
      radius: (d) => 3 + 11 * Math.sqrt(d.s.daily_trips / maxD),
      color: (d) => [...ramp(d.s.vulnerability, [[0, [34, 197, 94]], [0.5, [234, 179, 8]], [1, [239, 68, 68]]]), 235],
      line: (d) => (four.has(d.s.name) ? [255, 255, 255, 255] : [10, 13, 18, 255]), lineW: (d) => (four.has(d.s.name) ? 2.5 : 1),
      tipHtml: (d) => `<b>${nm(d.s.name)}</b>${row("Lines", d.s.lines.join(" / "))}${row("Typical day (2025)", fmt(d.s.daily_trips) + " trips")}${row("Apr / Mar 2024", fmt(d.s.apr_mar_2024 * 100) + "%")}${row("Vulnerability v", fmt(d.s.vulnerability, 2))}`,
    }),
    labelLayer("lbl", NET.stations.filter((s) => four.has(s.name)).map((s) => ({ p: pos(s), t: short(s.name) }))),
  ];
}
function dataPanel() {
  const st = NET.stations, four = NET.closures_2024;
  const lines = NET.lines;
  const km = (l) => NET.edges.filter((e) => e.line === l).reduce((a, e) => a + e.km, 0);
  const netRatio = NET.report.find((r) => r.startsWith("network-wide")).match(/([\d.]+)$/)[1];
  const drops = [...st].filter((s) => s.apr_mar_2024 != null).sort((a, b) => a.apr_mar_2024 - b.apr_mar_2024).slice(0, 12);
  const n = NET.network_params, fp = NET.flood_params;
  const sel4 = four.map((f) => st[IDX[f]]);
  return `
  <div class="kicker">Step 1 · Data</div><h1>What the AI works with</h1>
  <p class="lede">Every algorithm runs on a graph built from real RTA open data. The simulated parts are the storm, the crowd on the day and the response.</p>
  <div class="kpis">
    <div class="kpi"><div class="k">Stations</div><div class="v">${st.length}</div><div class="s">Red ${lines.Red.length} · Route 2020 ${lines["Route 2020"].length} · Green ${lines.Green.length}</div></div>
    <div class="kpi"><div class="k">Track (KML geometry)</div><div class="v">${fmt(km("Red") + km("Route 2020") + km("Green"), 1)} km</div><div class="s">Red ${fmt(km("Red") + km("Route 2020"), 1)} · Green ${fmt(km("Green"), 1)}</div></div>
    <div class="kpi"><div class="k">Graph</div><div class="v">${NET.graph_size.nodes} nodes</div><div class="s">${NET.graph_size.edges} directed edges · ${fmt(NET.n_bus_stops)} bus stops</div></div>
  </div>

  <h2>How the network becomes a graph</h2>
  <p>Each station becomes a <b>street node</b> (where passengers start and finish) plus one <b>platform node</b> per line. Edge cost is travel time in minutes:</p>
  <div class="formula">metro  platform → next   t = track_km ÷ <span class="v">${n.metro_speed_kmh}</span> km/h
entry  street ↔ platform t = <span class="v">${n.entry_exit_min}</span> min  <span class="c">(transfer = 4 min)</span>
walk   street ↔ street   t = km × <span class="v">${n.walk_detour}</span> ÷ <span class="v">${n.walk_speed_kmh}</span> km/h  <span class="c">(≤ ${n.walk_max_km} km)</span>
bus    added by policy   t = headway/2 + km × <span class="v">${n.road_detour}</span> ÷ <span class="v">${n.bus_speed_kmh}</span> km/h
<span class="c">A closed station loses its platform nodes, so trains
can't stop at it or pass through it.</span></div>

  <h2>Real evidence: the April 2024 ridership drop</h2>
  <p>April ÷ March 2024 trips per station. The whole network fell to <b>${fmt(netRatio * 100)}%</b>. The stations that closed fell much further:</p>
  ${Charts.bars({ items: drops.map((s) => ({ label: short(s.name), value: s.apr_mar_2024 * 100, color: four.includes(s.name) ? "#ef4444" : "#475569", bold: four.includes(s.name) })), fmt: (v) => v.toFixed(0) + "%", max: 100 })}
  <p class="hint">Red bars = the four stations that closed in 2024. We turn this drop into each station's flood vulnerability:</p>
  <div class="formula">r_i = (Apr_i / Mar_i) ÷ (Apr_net / Mar_net)
v_i = clip((1 − r_i) / 0.6, 0, 1)       <span class="c">vulnerability</span>
s_i = <span class="v">${fp.susceptibility_floor}</span> + ${fmt(1 - fp.susceptibility_floor, 2)} · v_i            <span class="c">susceptibility</span>

${sel4.map((s) => `${short(s.name).padEnd(10)} r = ${fmt(s.apr_mar_2024 / netRatio, 2)}  →  v = ${fmt(s.vulnerability, 2)}  →  s = <span class="r">${fmt(fp.susceptibility_floor + (1 - fp.susceptibility_floor) * s.vulnerability, 2)}</span>`).join("\n")}</div>

  <h2>Cleaning log (from the code)</h2>
  <div class="box"><ul style="margin:0;padding-left:18px;color:#c7d0dc">${NET.report.map((r) => `<li>${r}</li>`).join("")}</ul></div>`;
}

/* ================================================================ tab: FLOOD */
function floodSel() {
  if (sel) return IDX[sel];
  const w = SIM.water[step];
  let best = 0;
  w.forEach((v, i) => { if (v > w[best]) best = i; });
  if (w[best] > 0.5) return best;
  const first = SIM.closed_at.map((c, i) => [c, i]).filter(([c]) => c >= 0).sort((a, b) => a[0] - b[0])[0];
  return first ? first[1] : 0;
}
function floodLayers() {
  const [slon, slat, sint] = SIM.storm_track[step];
  const T = thr();
  legend([["ramp", "#334155,#0e7490,#0ea5e9,#bae6fd", `Water W / threshold (${T} mm)`], ["dot", "#64748b", "✕ Closed (W ≥ threshold)"], ["ring", "#94a3b8", "Storm cell (radius r)"]]);
  note(sint > 0 ? `Storm centre: ${fmt(sint)} mm/h` : SIM.hours[step] < SIM.storm.start_hour ? "Storm not started yet: press play" : "Storm has passed");
  const si = floodSel();
  return [...baseLayers(true),
    ...(sint > 0 ? [new ScatterplotLayer({ id: "storm", data: [1, 2], getPosition: () => [slon, slat], getRadius: (k) => SIM.storm.radius_km * 1000 * k,
      getFillColor: (k) => [148, 163, 184, k === 1 ? 22 : 10], stroked: true, getLineColor: [148, 163, 184, 120], lineWidthMinPixels: 1, updateTriggers: { getPosition: step } })] : []),
    stationLayer("st", {
      radius: (d) => 4 + 9 * Math.min(1, SIM.water[step][d.i] / T),
      color: (d) => (isClosed(d.i) ? [...C.grey, 255] : [...waterRGB(SIM.water[step][d.i] / T), 245]),
      line: (d) => (d.i === si ? [255, 255, 255, 255] : [10, 13, 18, 255]), lineW: (d) => (d.i === si ? 2.5 : 1),
      tipHtml: (d) => `<b>${nm(d.s.name)}</b>${row("Rain now", fmt(SIM.rain[step][d.i], 1) + " mm/h")}${row("Water W", fmt(SIM.water[step][d.i], 1) + " / " + T + " mm")}${row("Status", isClosed(d.i) ? "CLOSED" : "open")}`,
    }),
    closedX(),
    labelLayer("sel", [{ p: pos(NET.stations[si]), t: short(NET.stations[si].name) }]),
  ];
}
function floodPanel() {
  const T = thr(), fp = NET.flood_params, i = floodSel(), s = NET.stations[i];
  const sus = fp.susceptibility_floor + (1 - fp.susceptibility_floor) * s.vulnerability;
  const [slon, slat, sint] = SIM.storm_track[step];
  const d = hav(s.lat, s.lon, slat, slon);
  const b = fp.background_share, r = SIM.storm.radius_km;
  const spatial = b + (1 - b) * Math.exp(-(d * d) / (2 * r * r));
  const R = SIM.rain[step][i], Wp = step ? SIM.water[step - 1][i] : 0, W = SIM.water[step][i];
  const D = SIM.storm.drainage * fp.base_drainage_mmh;
  const top = SIM.water[0].map((_, j) => j).sort((a, c) => Math.max(...SIM.water.map((w) => w[c])) - Math.max(...SIM.water.map((w) => w[a]))).slice(0, 5);
  if (!top.includes(i)) top[4] = i;
  const cols = ["#38bdf8", "#f59e0b", "#a78bfa", "#22c55e", "#e879f9"];
  const cal = SIM.calibration;
  const closedList = NET.stations.filter((_, j) => SIM.closed_at[j] >= 0).map((x, _k) => ({ x, t: SIM.closed_at[IDX[x.name]] })).sort((a, c) => a.t - c.t);
  return `
  <div class="kicker">Step 2 · Flood model</div><h1>Which stations flood, and when?</h1>
  <p class="lede">A simple, transparent water-balance model, recomputed every 15 simulated minutes for all ${NET.stations.length} stations. A station closes when its water passes the threshold, and stays closed.</p>
  <h2>The equations, live for <b>${nm(s.name)}</b> at ${hhmm(SIM.hours[step])}</h2>
  <div class="formula">Rain at the station (mm/h)
  R = I(t) · [ b + (1−b) · exp(−d² / 2r²) ] · noise
    = <span class="v">${fmt(sint, 1)}</span> · [ ${b} + ${1 - b} · exp(−<span class="v">${fmt(d, 1)}</span>² / 2·${r}²) ] · noise
    = <span class="v">${fmt(sint, 1)}</span> · ${fmt(spatial, 3)} · noise  =  <span class="r">${fmt(R, 2)} mm/h</span>

Water balance over one step (Δt = 0.25 h)
  W(t) = max(0, W(t−Δt) + Δt · (s · R − D))
       = max(0, <span class="v">${fmt(Wp, 2)}</span> + 0.25 · (<span class="v">${fmt(sus, 2)}</span> · ${fmt(R, 2)} − <span class="v">${fmt(D, 1)}</span>))  =  <span class="r">${fmt(W, 2)} mm</span>

Close when W ≥ <span class="v">${T}</span> mm   →   ${isClosed(i) ? '<span class="r">CLOSED</span>' : `open (${fmt((100 * W) / T)}% of threshold)`}
<span class="c">I = storm-centre intensity     d = km to storm centre
r = ${r} km cell radius         b = ${b} background share
s = susceptibility (2024 data) D = drainage (mm/h)</span></div>
  <p class="hint">Click any station on the map to see its numbers. Drag the timeline to move through the day.</p>

  <h2>Water level over the day</h2>
  ${Charts.line({ x: SIM.hours, series: top.map((j, k) => ({ y: SIM.water.map((w) => w[j]), color: cols[k], label: short(NET.stations[j].name), width: j === i ? 2.6 : 1.5 })),
    hlines: [{ y: T, color: "#ef4444", label: `close at ${T} mm` }], vlines: [{ x: SIM.hours[step], color: "#94a3b8", dash: "3 3" }], xFmt: hhmm, yMin: 0, h: 210 })}

  <h2>Closures in this run</h2>
  <div class="box">${closedList.length ? closedList.map((c) => `<b>${hhmm(SIM.hours[c.t])}</b> ${nm(c.x.name)}`).join("<br>") : "No station reached the threshold."}</div>

  <h2>The replay uses the real closures</h2>
  <p>In the April 2024 replay, exactly the four stations that closed in 2024 close, and no others. The storm model only decides <b>when</b>: each closes the first time its water passes ${T} mm, or at its peak water level if it never does (Energy). Other scenarios use the flood model freely.</p>
  <h2>Validation: does the flood model alone find the right stations?</h2>
  <p>The threshold and drainage were calibrated by a grid search (<b>47 thresholds × 12 drainage rates × 10 seeds</b>), keeping the pair whose <i>unforced</i> flood model best matches the real closures.</p>
  <div class="formula">threshold = <span class="r">${T} mm</span>   drainage = <span class="r">${fp.base_drainage_mmh} mm/h</span>
${cal ? `real 2024 closures  : ${cal.target.map(short).join(", ")}
flood model alone   : ${(cal.flood_only_closed || []).map(short).join(", ") || "none"}
this run            : precision ${cal.precision}, recall ${cal.recall}` : "Select the April 2024 replay to see the validation."}${RES && RES.calibration ? `
over ${RES.calibration.seeds} runs        : precision ${pmf(RES.calibration.precision_mean, RES.calibration.precision_std, 3)}, recall ${pmf(RES.calibration.recall_mean, RES.calibration.recall_std, 3)}` : ""}</div>
  <p class="hint">A calibration, not a forecast. Energy is missed because its April ridership fell least (−45%), giving it the lowest susceptibility of the four. Also note the signal is partly circular: these stations' ridership dropped partly <i>because</i> they closed.</p>`;
}

/* ================================================================ tab: FUZZY */
function fuzzyInputs(i, t = step) {
  const st = stateAt(t);
  return { load: SIM.steps.ai[t].ratio[i], flood: SIM.water[t][i] / thr(), hub: NET.stations[i].interchange ? 1 : 0, dist: st && st.dist ? st.dist[i] : 10 };
}
function fuzzySel() {
  if (sel) return IDX[sel];
  const p = SIM.steps.ai[step].priority;
  let best = 0;
  p.forEach((v, i) => { if (!isClosed(i) && v > p[best]) best = i; });
  return best;
}
function fuzzyLayers() {
  const S = SIM.steps.ai[step], si = fuzzySel();
  legend([["ramp", "#22c55e,#eab308,#f97316,#ef4444", "Priority 0 → 100 (Low → Critical)"], ["dot", "#94a3b8", "Size = load ratio"], ["ring", "#ef4444", "Critical (≥ 80)"]]);
  note("Colour = fuzzy priority at this moment. Click a station to see its inference step by step.");
  return [...baseLayers(true),
    stationLayer("st", {
      radius: (d) => 4 + 7 * Math.min(2, S.ratio[d.i]),
      color: (d) => (isClosed(d.i) ? [...C.grey, 230] : [...prioRGB(S.priority[d.i]), 240]),
      line: (d) => (d.i === si ? [255, 255, 255, 255] : S.priority[d.i] >= 80 && !isClosed(d.i) ? [239, 68, 68, 255] : [10, 13, 18, 255]),
      lineW: (d) => (d.i === si ? 3 : S.priority[d.i] >= 80 ? 2 : 1),
      tipHtml: (d) => `<b>${nm(d.s.name)}</b>${row("Priority", `${fmt(S.priority[d.i])} · ${label(S.priority[d.i])}`)}${row("Load ratio", fmt(S.ratio[d.i] * 100) + "%")}`,
    }),
    closedX(),
    labelLayer("sel", [{ p: pos(NET.stations[si]), t: short(NET.stations[si].name) }]),
  ];
}
function mfChart(v, x, color, title) {
  const cols = ["#22c55e", "#38bdf8", "#f59e0b", "#ef4444"];
  const terms = Object.keys(v.terms);
  return `<div class="box" style="padding:8px 10px"><div class="hint" style="margin-bottom:2px"><b>${title}</b> = ${fmt(x, 2)}</div>
  ${Charts.line({ x: v.x, series: terms.map((t, k) => ({ y: v.terms[t], color: cols[k % 4], label: t })), vlines: [{ x: Math.min(Math.max(x, v.x[0]), v.x[v.x.length - 1]), color: "#fff", width: 1.6 }], yMin: 0, yMax: 1, h: 120, w: 300, xTicks: 4, margin: { l: 26 } })}</div>`;
}
async function fuzzyPanel() {
  const i = fuzzySel(), s = NET.stations[i], inp = fuzzyInputs(i);
  const key = [inp.load, inp.flood, inp.hub, inp.dist].map((v) => v.toFixed(3)).join(",");
  let e = fuzzyCache.get(key);
  if (!e) {
    e = await (await fetch(`/api/fuzzy?load=${inp.load}&flood=${inp.flood}&hub=${inp.hub}&dist=${inp.dist}`)).json();
    fuzzyCache.set(key, e);
  }
  if (tab !== "fuzzy") return null;
  const deg = (v) => Object.entries(e.degrees[v]).filter(([, d]) => d > 0).map(([t, d]) => `${t} ${fmt(d, 2)}`).join(", ") || "none";
  const fired = e.rules.filter((r) => r.strength > 0);
  const simP = SIM.steps.ai[step].priority[i];
  const outCols = { low: "#22c55e", medium: "#eab308", high: "#f97316", critical: "#ef4444" };
  return `
  <div class="kicker">Step 3 · Fuzzy logic (Mamdani)</div><h1>How urgently does each station need help?</h1>
  <p class="lede">Operators think in vague terms: "very crowded", "next to a closure", "badly flooded". Fuzzy logic turns these into one 0–100 priority. That number colours the map, sends staff, and feeds the genetic algorithm.</p>
  <h2>Inputs for <b>${nm(s.name)}</b> at ${hhmm(SIM.hours[step])}</h2>
  <div class="formula">load ratio  (load ÷ capacity)   = <span class="v">${fmt(inp.load, 3).padEnd(6)}</span> → ${deg("load")}
flood risk  (water ÷ threshold) = <span class="v">${fmt(inp.flood, 3).padEnd(6)}</span> → ${deg("flood")}
interchange                     = <span class="v">${String(inp.hub).padEnd(6)}</span> → ${deg("hub")}
stops to nearest closure        = <span class="v">${fmt(inp.dist).padEnd(6)}</span> → ${deg("dist")}</div>

  <h2>① Fuzzify: how much does each input belong to each word?</h2>
  <p class="hint">Triangular and trapezoidal membership functions. The white line is this station's value, and where it crosses a curve is its degree (0–1).</p>
  <div class="row2">${mfChart(e.mf.load, e.clipped.load, 0, "Load ratio")}${mfChart(e.mf.flood, e.clipped.flood, 0, "Flood risk")}${mfChart(e.mf.dist, e.clipped.dist, 0, "Stops to closure")}${mfChart(e.mf.hub, e.clipped.hub, 0, "Interchange")}</div>

  <h2>② Apply the ${e.rules.length} rules (AND = min)</h2>
  <p class="hint">A rule fires as strongly as its <b>weakest</b> condition. ${fired.length} of ${e.rules.length} rules fire here.</p>
  <div class="scroll"><table class="t"><tr><th>#</th><th>IF</th><th>THEN</th><th class="n">strength</th></tr>
  ${e.rules.map((r) => `<tr class="${r.strength > 0 ? "hl" : "dim"}"><td>${r.id}</td><td>${r.if.map((c) => `${c.var} is <b>${c.term}</b> <span class="muted">(${fmt(c.degree, 2)})</span>`).join(" AND ")}</td>
    <td><span class="pill" style="background:${outCols[r.then]}22;color:${outCols[r.then]}">${r.then}</span></td><td class="n">${r.strength > 0 ? `<b>${fmt(r.strength, 2)}</b>` : "0"}</td></tr>`).join("")}</table></div>

  <h2>③ Aggregate (max of clipped outputs) and ④ defuzzify (centroid)</h2>
  ${Charts.line({ x: e.output.x, series: [...Object.entries(e.output.terms).map(([t, y]) => ({ y, color: outCols[t] + "66", label: t, width: 1 })), { y: e.output.aggregate, color: "#38bdf8", fill: "rgba(56,189,248,.25)", width: 2.2, label: "aggregate" }],
    vlines: [{ x: e.centroid, color: "#fff", label: `centroid ${fmt(e.centroid, 1)}`, width: 2 }], yMin: 0, yMax: 1, h: 170, xFmt: (v) => v.toFixed(0) })}
  <div class="formula">priority = Σ μ(y)·y ÷ Σ μ(y)  over y ∈ [0, 100]  =  <span class="r">${fmt(e.centroid, 1)}  →  ${e.label}</span>
<span class="c">simulation value at this step: ${fmt(simP, 1)} (same code; any small gap is from the inputs being rounded for display)</span></div>
  <p class="hint">Every rule and membership function is in <span class="mono">src/ai/fuzzy.py</span>. Click another station to compare, e.g. one far from the closure.</p>`;
}

/* ================================================================ tab: SEARCH */
async function loadSearch(origin, dest) {
  const fs = finalState();
  const r = await fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ origin, dest, closed: SIM.closed_final }) });
  SEARCH = await r.json();
  searchK = 0; searchAnim = true;
}
function searchLayers() {
  if (!SEARCH) { legend([]); return baseLayers(); }
  const A = SEARCH.astar, D = SEARCH.dijkstra;
  const maxK = Math.max(A.trace.length, D.trace.length);
  const k = Math.min(searchK, maxK);
  legend([["ring", "#e879f9", `Dijkstra expanded (${Math.min(k, D.trace.length)}/${D.expanded})`], ["dot", "#22d3ee", `A* expanded (${Math.min(k, A.trace.length)}/${A.expanded})`], ["line", "#fde047", "Bus edge"], ["line", "#64748b", "Walk edge"], ["line", "#fff", "Optimal path"]]);
  note(k >= maxK ? `Both found the same ${fmt(A.cost, 1)}-minute route. A* expanded ${A.expanded} nodes, Dijkstra ${D.expanded}.` : `Expansion ${k}: each search pops the node with the smallest key from its priority queue`);
  const showA = searchMode !== "dijkstra", showD = searchMode !== "astar";
  const layers = [
    new LineLayer({ id: "edges", data: SEARCH.graph.filter((e) => e.mode === "walk"), getSourcePosition: (d) => d.a, getTargetPosition: (d) => d.b,
      getColor: [100, 116, 139, 110], getWidth: 1, widthUnits: "pixels" }),
    // bus edges link every pair of stops on a route (one wait, ride through); draw the route itself instead of the fan
    new PathLayer({ id: "busr", data: (finalState() ? finalState().baseline.routes : []), getPath: (r) => r.coords, getColor: [253, 224, 71, 170], getWidth: 2.5, widthUnits: "pixels", jointRounded: true }),
    ...baseLayers(true),
    stationLayer("st", { radius: 3, color: (d) => (isClosed(d.i, SIM.hours.length - 1) ? [...C.grey, 255] : [148, 163, 184, 200]), pickable: false }),
    closedX(SIM.hours.length - 1),
  ];
  if (showD) layers.push(new ScatterplotLayer({ id: "dij", data: D.trace.slice(0, k), getPosition: (t) => [t.lon, t.lat], getRadius: 9, radiusUnits: "pixels", filled: false, stroked: true, getLineColor: [...C.pink, 230], lineWidthMinPixels: 2 }));
  if (showA) layers.push(new ScatterplotLayer({ id: "ast", data: A.trace.slice(0, k), getPosition: (t) => [t.lon, t.lat], getRadius: 4.5, radiusUnits: "pixels", getFillColor: [...C.cyan, 255] }));
  if (k >= maxK) layers.push(new PathLayer({ id: "path", data: [A.path.map((p) => [p.lon, p.lat])], getPath: (d) => d, getColor: [255, 255, 255, 240], getWidth: 4, widthUnits: "pixels", capRounded: true, jointRounded: true }));
  const o = A.path[0], g = A.path[A.path.length - 1];
  layers.push(labelLayer("od", [{ p: [o.lon, o.lat], t: "START " + short(SEARCH.origin) }, { p: [g.lon, g.lat], t: "GOAL " + short(SEARCH.dest) }], [255, 255, 255], 12.5));
  return layers;
}
function searchPanel() {
  const opts = (v) => NET.stations.map((s) => `<option value="${s.name}" ${s.name === v ? "selected" : ""}>${short(s.name)}</option>`).join("");
  if (!SEARCH) return `<div class="kicker">Step 4 · Search</div><h1>Loading search…</h1>`;
  const A = SEARCH.astar, D = SEARCH.dijkstra, k = searchK;
  const saved = 100 * (1 - A.expanded / D.expanded);
  const rows = A.trace.map((t, j) => `<tr class="${j === Math.min(k, A.trace.length) - 1 ? "hl" : j >= k ? "dim" : ""}"><td class="n">${j + 1}</td><td>${t.node}</td><td class="n">${fmt(t.g, 2)}</td><td class="n">${fmt(t.h, 2)}</td><td class="n"><b>${fmt(t.f, 2)}</b></td></tr>`).join("");
  const modeCount = {};
  A.modes.forEach((m) => (modeCount[m] = (modeCount[m] || 0) + 1));
  return `
  <div class="kicker">Step 4 · A* search vs Dijkstra</div><h1>How do stranded passengers get around the closure?</h1>
  <p class="lede">Each displaced trip is routed on the disrupted graph (${SEARCH.nodes} nodes, ${SEARCH.edges} edges: trains, walking, shuttle buses). Both algorithms find the fastest route. A* gets there by exploring far less.</p>
  <div class="ctrl"><span class="hint">From</span><select id="sOrig">${opts(SEARCH.origin)}</select><span class="hint">to</span><select id="sDest">${opts(SEARCH.dest)}</select>
    <span class="seg" id="sMode"><button data-v="both" class="${searchMode === "both" ? "on" : ""}">Both</button><button data-v="astar" class="${searchMode === "astar" ? "on" : ""}">A*</button><button data-v="dijkstra" class="${searchMode === "dijkstra" ? "on" : ""}">Dijkstra</button></span></div>
  <div class="ctrl"><button class="icon" id="sPlay">${searchAnim ? "❚❚" : "▶"}</button><input type="range" id="sK" min="0" max="${Math.max(A.trace.length, D.trace.length)}" value="${k}"><span class="mono hint">expansion ${k}</span></div>
  <div class="kpis">
    <div class="kpi"><div class="k">Nodes expanded</div><div class="v"><span style="color:#22d3ee">${A.expanded}</span> vs <span style="color:#e879f9">${D.expanded}</span></div><div class="s">A* vs Dijkstra · <b class="good">${fmt(saved)}% fewer</b></div></div>
    <div class="kpi"><div class="k">Route time</div><div class="v">${fmt(A.cost, 1)} min</div><div class="s">Dijkstra: ${fmt(D.cost, 1)} min (identical)</div></div>
    <div class="kpi"><div class="k">Queue pushes</div><div class="v">${A.pushes} vs ${D.pushes}</div><div class="s">runtime ${fmt(A.runtime_ms, 2)} vs ${fmt(D.runtime_ms, 2)} ms</div></div>
  </div>
  ${RES && RES.search ? (() => {
    const f = (m, a) => RES.search.find((r) => r.measure.startsWith(m) && (!a || r.algorithm === a));
    return `<div class="box"><b>Benchmark: ${f("Trips with identical").mean} random trips</b> on the disrupted replay network. Nodes expanded: A* ${pmf(f("Nodes expanded", "A*").mean, f("Nodes expanded", "A*").std, 1)} vs Dijkstra ${pmf(f("Nodes expanded", "Dijkstra").mean, f("Nodes expanded", "Dijkstra").std, 1)} (A* saves ${pmf(f("A* expansion saving").mean, f("A* expansion saving").std, 1)}%). Identical optimal cost on ${f("Trips with identical").mean}/${f("Trips with identical").mean} trips (also checked against networkx). Runtime: A* ${pmf(f("Runtime", "A*").mean, null, 3)} ms vs Dijkstra ${pmf(f("Runtime", "Dijkstra").mean, null, 3)} ms. On a graph this small, computing h costs about as much as the expansions it saves.</div>`;
  })() : ""}
  <h2>The idea</h2>
  <div class="formula">Dijkstra pops the node with the smallest   g(n)
A*       pops the node with the smallest   f(n) = g(n) + h(n)

g(n) = minutes already travelled from the start
h(n) = straight-line km to the goal ÷ v_max × 60,   v_max = <span class="v">${SEARCH.vmax_kmh}</span> km/h (fastest mode)

<span class="c">Why h is admissible (never overestimates):
  every edge costs ≥ its straight-line length ÷ v_max
  (track ≥ straight line; walk and bus are slower and add waits)
  ⇒ h(n) ≤ true remaining time ⇒ A* returns the optimal route.</span></div>
  <h2>The route found</h2>
  <div class="box">${A.path.filter((p) => !p.node.includes("platform") || true).map((p, j) => (j ? ` <span class="muted">—${A.modes[j - 1]}→</span> ` : "") + `<b>${p.node.replace(" (street)", "")}</b>`).join("")}</div>
  <p class="hint">Edges used: ${Object.entries(modeCount).map(([m, c]) => `${c} × ${m}`).join(", ")}.</p>
  <h2>A* expansion trace (from the real run)</h2>
  <p class="hint">Note how A* expands in increasing <b>f</b>: nodes heading away from the goal get a large h and are never popped.</p>
  <div class="scroll"><table class="t"><tr><th class="n">#</th><th>node popped</th><th class="n">g (min)</th><th class="n">h (min)</th><th class="n">f = g + h</th></tr>${rows}</table></div>
  <h2>Key of each popped node</h2>
  ${Charts.line({ x: Array.from({ length: Math.max(A.trace.length, D.trace.length) }, (_, j) => j + 1), series: [
    { y: D.trace.map((t) => t.g), color: "#e879f9", label: "Dijkstra key g" }, { y: A.trace.map((t) => t.f).concat(Array(Math.max(0, D.trace.length - A.trace.length)).fill(null)), color: "#22d3ee", label: "A* key f = g + h" }],
    hlines: [{ y: A.cost, color: "#fff", label: "optimal cost" }], yMin: 0, h: 170, xFmt: (v) => v.toFixed(0) })}
  <p class="hint">Dijkstra must pop <i>every</i> node closer than the goal. A* starts with a good estimate (f ≈ ${fmt(A.trace[0].f, 0)} min) and only pops nodes whose f is below the optimal cost.</p>`;
}

/* ================================================================ tab: BRIDGE */
function bridgeLayers() {
  const fs = finalState();
  if (!fs) { legend([]); note("No closures in this run."); return baseLayers(); }
  const designs = fs.terminal_designs || [];
  const cand = new Set(designs.flatMap((d) => [d.a, d.b]).filter(Boolean));
  const aiR = fs.ai.routes, bR = fs.baseline.routes;
  legend([["line", "#a78bfa", "AI bus bridge (searched terminals)"], ["line", "#94a3b8", "2024-style bridge (adjacent stations)"], ["ring", "#f59e0b", "Candidate terminals"], ["dot", "#64748b", "✕ Closed / cut off"]]);
  note("The AI tries every terminal pair and keeps the one with the lowest cost J");
  const chosen = new Set(Object.values(fs.terminals || {}).flat().filter(Boolean));
  return [...baseLayers(true),
    new PathLayer({ id: "bb", data: bR, getPath: (r) => r.coords, getColor: [148, 163, 184, 200], getWidth: 7, widthUnits: "pixels", capRounded: true, jointRounded: true }),
    new PathLayer({ id: "ab", data: aiR, getPath: (r) => r.coords, getColor: [...C.violet, 230], getWidth: 3, widthUnits: "pixels", capRounded: true, jointRounded: true }),
    stationLayer("st", { radius: (d) => (cand.has(d.s.name) ? 7 : 3.5), color: (d) => (fs.displaced.includes(d.s.name) ? [...C.grey, 255] : chosen.has(d.s.name) ? [...C.violet, 255] : [148, 163, 184, 200]),
      line: (d) => (cand.has(d.s.name) ? [...C.amber, 255] : [10, 13, 18, 255]), lineW: (d) => (cand.has(d.s.name) ? 2 : 1),
      tipHtml: (d) => `<b>${nm(d.s.name)}</b>${row("Role", fs.displaced.includes(d.s.name) ? "closed / no rail" : chosen.has(d.s.name) ? "chosen terminal" : cand.has(d.s.name) ? "candidate terminal" : "-")}` }),
    closedX(SIM.hours.length - 1),
    labelLayer("lbl", [...cand].map((n) => ({ p: pos(NET.stations[IDX[n]]), t: short(n) }))),
  ];
}
function bridgePanel() {
  const fs = finalState();
  if (!fs) return `<div class="kicker">Step 5 · Bus bridge</div><h1>No closures in this run</h1><p class="lede">Pick the April 2024 replay or the extreme storm.</p>`;
  const designs = fs.terminal_designs || [];
  const pp = NET.policy_params;
  const byBreak = {};
  designs.forEach((d) => (byBreak[d.break] = byBreak[d.break] || []).push(d));
  const route = (r) => `${r.stops.map(short).join(" → ")} <span class="muted">· ${r.buses} buses, every ${r.headway_min} min</span>`;
  return `
  <div class="kicker">Step 5 · Bus design, evaluated with A*</div><h1>Where should the replacement buses run?</h1>
  <p class="lede">A <b>break</b> is a run of consecutive stations with no train service. In 2024 the shuttle ran between the stations either side of the break. The AI scores every candidate design by routing all stranded passengers on it with crowd-aware A* (part of the response design, not a separate AI technique). Ending one or two stops further out, or adding a split shuttle, can avoid dumping everyone at an already-crowded station.</p>
  <h2>Search space and objective</h2>
  <div class="formula">for each break:
  A = up to <span class="v">${pp.terminal_reach}</span> open stations before it
  B = up to <span class="v">${pp.terminal_reach}</span> open stations after it
  for each pair (a, b) in A × B:
     add bus route  a → closed stations → b
     route every sampled trip with crowd-aware A*
     J(a,b) = avg extra min + <span class="v">10</span>·Σ overload + <span class="v">100</span>·unserved
  choose (a, b) = argmin J
<span class="c">${designs.length} designs evaluated in this run</span></div>
  ${Object.entries(byBreak).map(([b, ds]) => {
    const best = Math.min(...ds.map((d) => d.objective));
    const sorted = [...ds].sort((x, y) => x.objective - y.objective);
    return `<h2>Break ${+b + 1}: ${fs.breaks[b] ? fs.breaks[b].closed.map(short).join(", ") : ""}</h2>
    ${Charts.bars({ items: sorted.map((d) => ({ label: `${short(d.a || "–")} ⇄ ${short(d.b || "–")}`, value: d.objective, color: d.objective === best ? "#a78bfa" : "#334155", bold: d.objective === best })), fmt: (v) => "J = " + v.toFixed(1), labelW: 220 })}
    <div class="scroll" style="max-height:200px"><table class="t"><tr><th>terminals</th><th class="n">avg extra min</th><th class="n">Σ overload</th><th class="n">unserved</th><th class="n">J</th></tr>
    ${sorted.map((d) => `<tr class="${d.objective === best ? "win" : ""}"><td>${short(d.a || "–")} ⇄ ${short(d.b || "–")}</td><td class="n">${fmt(d.avg_extra, 1)}</td><td class="n">${fmt(d.overload, 2)}</td><td class="n">${fmt(d.unserved * 100, 1)}%</td><td class="n"><b>${fmt(d.objective, 1)}</b></td></tr>`).join("")}</table></div>`;
  }).join("")}
  <h2>Result: bus routes and fleet split (same ${pp.bus_fleet} buses for both)</h2>
  <div class="box"><b>AI</b><br>${fs.ai.routes.map(route).join("<br>")}<br><br><b>2024-style</b><br>${fs.baseline.routes.map(route).join("<br>")}</div>
  <div class="formula">headway = round-trip time ÷ buses on the route
AI fleet split ∝ displaced demand × round-trip time      <span class="c">(2024-style: equal split)</span></div>`;
}

/* ================================================================ tab: GA */
function gaLayers() {
  const fs = finalState();
  if (!fs) { legend([]); note("No closures in this run."); return baseLayers(); }
  const g = fs.ga;
  const hubs = gaShow === "ga" ? g.hubs : g.greedy_hubs;
  const hubPos = Object.fromEntries(hubs.map((h) => [h.name, [h.lon, h.lat]]));
  const links = gaShow === "ga" ? g.nearest_hub.filter((l) => hubPos[l.hub]).map((l) => ({ a: pos(NET.stations[IDX[l.station]]), b: hubPos[l.hub], m: l.minutes })) : [];
  legend([["dot", "#475569", `Candidate sites (${g.n_candidates})`], ["dot", gaShow === "ga" ? "#a78bfa" : "#f59e0b", gaShow === "ga" ? "GA hubs (k = 5)" : "Greedy hubs"], ["line", "#a78bfa", "Displaced station → nearest hub"], ["dot", "#64748b", "✕ Closed / cut off"]]);
  note(gaShow === "ga" ? "Each purple hub is one gene of the best chromosome" : "Greedy: add the single best hub, 5 times");
  return [...baseLayers(true),
    new ScatterplotLayer({ id: "cands", data: g.candidates, getPosition: (c) => [c.lon, c.lat], getRadius: 2.2, radiusUnits: "pixels", getFillColor: (c) => (c.kind === "station" ? [100, 116, 139, 200] : [71, 85, 105, 170]) }),
    stationLayer("st", { radius: 3.5, color: (d) => (fs.displaced.includes(d.s.name) ? [...C.grey, 255] : [148, 163, 184, 180]), pickable: false }),
    closedX(SIM.hours.length - 1),
    new LineLayer({ id: "links", data: links, getSourcePosition: (d) => d.a, getTargetPosition: (d) => d.b, getColor: [...C.violet, 200], getWidth: 2, widthUnits: "pixels" }),
    new ScatterplotLayer({ id: "hubs", data: hubs, getPosition: (h) => [h.lon, h.lat], getRadius: 8, radiusUnits: "pixels", getFillColor: gaShow === "ga" ? [...C.violet, 255] : [...C.amber, 255], stroked: true, getLineColor: [255, 255, 255, 255], lineWidthMinPixels: 2, pickable: true,
      onHover: (info) => tip(info, (h) => `<b>${h.name}</b>${row("Type", h.kind === "bus_stop" ? "real bus stop" : "metro station")}`) }),
    labelLayer("hl", hubs.map((h) => ({ p: [h.lon, h.lat], t: h.name.length > 26 ? h.name.slice(0, 24) + "…" : h.name, o: [0, -16] }))),
    labelLayer("ml", links.map((l) => ({ p: [(l.a[0] + l.b[0]) / 2, (l.a[1] + l.b[1]) / 2], t: fmt(l.m, 1) + " min", o: [0, 0] })), [196, 181, 253], 10.5),
  ];
}
function comb(n, k) { let r = 1; for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i; return r; }
function gaPanel() {
  const fs = finalState();
  if (!fs) return `<div class="kicker">Step 6 · Genetic algorithm</div><h1>No closures in this run</h1>`;
  const g = fs.ga, p = g.params, B = g.breakdown;
  const gens = g.curve_best.map((_, j) => j);
  const termRow = (k, lbl) => `<tr><td>${lbl}</td>${["ga", "greedy", "random"].map((m) => `<td class="n">${fmt(B[m][k], 3)}</td>`).join("")}</tr>`;
  return `
  <div class="kicker">Step 6 · Genetic algorithm</div><h1>Where should the ${p.k} relief hubs go?</h1>
  <p class="lede">A relief hub is where staff, water, information and taxis are set up. Candidates are the ${g.n_candidates} open stations and real bus stops within walking reach of a closure. Choosing ${p.k} of them gives <b>${fmt(comb(g.n_candidates, p.k))}</b> possible combinations, far too many to try. The GA evolves good combinations instead.</p>
  <div class="ctrl"><span class="seg" id="gaSeg"><button data-v="ga" class="${gaShow === "ga" ? "on" : ""}">GA solution</button><button data-v="greedy" class="${gaShow === "greedy" ? "on" : ""}">Greedy solution</button></span></div>
  <h2>Chromosome = a set of ${p.k} unique sites</h2>
  <div class="chrom">${g.hubs.map((h, j) => `<div class="gene"><small>gene ${j + 1} · ${h.kind === "bus_stop" ? "bus stop" : "station"}</small>${h.name}</div>`).join("")}</div>
  <p class="hint">Best chromosome in generation 0 (random): ${g.first_gen_hubs.join(", ")}.</p>

  <h2>Fitness: what "good" means</h2>
  <div class="formula">F(H) =        Σ_s d_s · c(t_sH) / Σ d_s      <span class="c">① displaced people reach a hub</span>
     + <span class="v">${p.w_p}</span> · Σ_i p_i · c(t_iH) / Σ p_i      <span class="c">② urgent stations covered</span>
     − <span class="v">${p.w_o}</span> · mean_h max(0, load_h − 1)      <span class="c">③ avoid overloaded stations</span>
     − <span class="v">${p.w_t}</span> · mean minutes to hub ÷ 60       <span class="c">④ closer is better</span>

c(t) = 1 if t ≤ T (<span class="v">${p.T}</span> min), else e^(−(t−T)/T)
<span class="c">d_s = displaced demand at s, p_i = fuzzy priority above 30,
t   = minutes by Dijkstra on the disrupted graph (+ walk to bus stops)</span></div>
  <table class="t box"><tr><th>term</th><th class="n">GA</th><th class="n">greedy</th><th class="n">random</th></tr>
    ${termRow("cover_displaced", "displaced coverage")}${termRow("cover_priority", "priority coverage")}${termRow("overload_penalty", "overload penalty")}${termRow("time_penalty", "time penalty")}
    <tr><td><b>fitness F</b></td>${["ga", "greedy", "random"].map((m) => `<td class="n"><b>${fmt(B[m].total, 3)}</b></td>`).join("")}</tr>
    <tr><td class="muted">mean minutes to hub</td>${["ga", "greedy", "random"].map((m) => `<td class="n muted">${fmt(B[m].mean_minutes_to_hub, 1)}</td>`).join("")}</tr></table>

  <h2>Evolution (${p.generations} generations × population ${p.population})</h2>
  ${Charts.line({ x: gens, series: [{ y: g.curve_best, color: "#a78bfa", label: "best", width: 2.4 }, { y: g.curve_mean, color: "#a78bfa88", label: "mean" }, { y: g.curve_worst, color: "#475569", label: "worst" }],
    hlines: [{ y: g.greedy, color: "#f59e0b", label: "greedy" }, { y: g.random, color: "#64748b", label: "random" }], h: 190, xFmt: (v) => v.toFixed(0) })}
  <p class="hint">Population diversity (share of candidates present in the population): ${fmt(g.diversity[0] * 100)}% at the start → ${fmt(g.diversity[g.diversity.length - 1] * 100)}% at the end. It converges.</p>
  <h2>Operators</h2>
  <ol class="steps">
    <li><b>Selection:</b> ${p.selection}, size ${p.tournament_size}. Pick ${p.tournament_size} random chromosomes and keep the fittest as a parent.</li>
    <li><b>Crossover</b> (p = ${p.crossover_rate}): set-preserving. Keep the sites both parents share, then fill from the rest of their union.</li>
    <li><b>Mutation</b> (p = ${p.mutation_rate}): swap one site for a random site not already in the set.</li>
    <li><b>Repair:</b> remove duplicates and top up, so every chromosome is always ${p.k} unique valid sites.</li>
    <li><b>Elitism:</b> the best ${p.elitism} survive unchanged, so the best fitness never gets worse.</li>
  </ol>
  <h2>Baseline 1: greedy (add the best single hub each step)</h2>
  <table class="t box"><tr><th>step</th><th>hub added</th><th class="n">fitness after</th></tr>${g.greedy_steps.map((s, j) => `<tr><td>${j + 1}</td><td>${s.name}</td><td class="n">${fmt(s.fitness, 3)}</td></tr>`).join("")}</table>
  <p class="hint">Greedy can't undo an early choice. The GA searches whole combinations, so it finds sets of hubs that work well together.</p>
  ${RES && RES.ga ? (() => {
    const row = (m) => RES.ga.find((r) => r.scenario === "april_2024_replay" && r.method === m);
    const ga = row("ga"), gr = row("greedy"), rn = row("random"), ge = row("GA >= greedy (seeds)");
    return ga ? `<h2>Across ${ga.n} runs (April 2024 replay, seeds 0–${ga.n - 1})</h2>
    <table class="t box"><tr><th>method</th><th class="n">fitness</th><th class="n">covered ≤ ${p.T} min</th><th class="n">mean min to hub</th></tr>
    ${[["GA", ga], ["greedy", gr], ["random", rn]].map(([n, r]) => `<tr><td>${n}</td><td class="n">${pmf(r.fitness_mean, r.fitness_std, 3)}</td><td class="n">${pmf(100 * r.covered_mean, 100 * r.covered_std, 1)}%</td><td class="n">${pmf(r.minutes_to_hub_mean, r.minutes_to_hub_std, 1)}</td></tr>`).join("")}</table>
    <p class="hint">GA ≥ greedy in ${ge ? ge.fitness_mean : "–"}/${ga.n} runs. Greedy is a strong baseline for this coverage objective; the GA matches it and is far above random. Convergence plot: results/figures/ga_convergence.png.</p>` : "";
  })() : ""}
  <h2>Baseline 2: random placement</h2><p>Fitness <b>${fmt(g.random, 3)}</b>. Coverage within ${p.T} min: GA <b>${fmt(g.covered_ga * 100)}%</b> · greedy ${fmt(g.covered_greedy * 100)}% · random ${fmt(g.covered_random * 100)}%.</p>`;
}

/* ================================================================ tab: RESULTS */
function resultsLayers() {
  const S = SIM.steps[resPolicy][step], st = stateAt(step);
  const plan = st && st[resPolicy];
  legend([["ramp", "#22c55e,#eab308,#ef4444,#be123c", "Load ÷ capacity (0 → 200%)"], ["dot", "#94a3b8", "Size = passengers per 15 min"], ["dot", resPolicy === "ai" ? "#a78bfa" : "#cbd5e1", "Relief points"], ["line", "#fde047", "Bus bridge"]]);
  note(`${resPolicy === "ai" ? "AI response" : "2024-style response (model)"} at ${hhmm(SIM.hours[step])}`);
  const maxL = Math.max(...SIM.capacity);
  return [...baseLayers(true),
    ...(plan ? [new PathLayer({ id: "bus", data: plan.routes, getPath: (r) => r.coords, getColor: [253, 224, 71, 170], getWidth: 3, widthUnits: "pixels", jointRounded: true })] : []),
    stationLayer("st", {
      radius: (d) => (isClosed(d.i) ? 4 : 3 + 12 * Math.sqrt(S.load[d.i] / maxL)),
      color: (d) => (isClosed(d.i) ? [...C.grey, 255] : [...loadRGB(S.ratio[d.i]), 235]),
      tipHtml: (d) => `<b>${nm(d.s.name)}</b>${row("Load / 15 min", fmt(S.load[d.i]))}${row("Capacity proxy", fmt(SIM.capacity[d.i]))}${row("Load ratio", fmt(S.ratio[d.i] * 100) + "%")}${row("Priority", fmt(S.priority[d.i]) + " " + label(S.priority[d.i]))}`,
    }),
    closedX(),
    ...(plan ? [new ScatterplotLayer({ id: "relief", data: plan.relief, getPosition: (h) => [h.lon, h.lat], getRadius: 7, radiusUnits: "pixels", getFillColor: resPolicy === "ai" ? [...C.violet, 255] : [203, 213, 225, 255], stroked: true, getLineColor: [10, 13, 18, 255], lineWidthMinPixels: 2 })] : []),
  ];
}
function resultsPanel() {
  const a = SIM.summary.ai, b = SIM.summary.baseline;
  const A = SIM.steps.ai, B = SIM.steps.baseline;
  const rows = [
    ["People who gave up on the metro", "gave_up", 0, "lo", "", "Crowd-aware A* (routing + bus design)"],
    ["Hours spent queuing", "waiting_person_hours", 0, "lo", " h", "Crowd-aware A* (routing + bus design)"],
    ["Peak people waiting", "peak_waiting", 0, "lo", "", "Crowd-aware A* (routing + bus design)"],
    ["Within 10 min of relief", "covered_pct", 1, "hi", "%", "Genetic algorithm (hub placement)"],
    ["Peak load ratio", "peak_ratio", 2, "lo", "×", "Crowd-aware A* (routing + bus design)"],
    ["Max overloaded stations", "max_overloaded_stations", 0, "lo", "", "Crowd-aware A* (routing + bus design)"],
    ["Avg extra trip time", "avg_extra_min", 1, "lo", " min", "A* (trade-off: crowd penalty)"],
    ["95th pct extra time", "p95_extra_min", 1, "lo", " min", "A*"],
    ["Unserved", "unserved_pct", 1, "lo", "%", "Bus design (A*) + fleet split"],
    ["Critical stations staffed", "staffed_critical_pct", 0, "hi", "%", "Fuzzy priority (staff dispatch)"],
  ];
  const tr = rows.map(([l, k, d, dir, u, alg]) => {
    const x = b[k], y = a[k];
    const diff = x != null && y != null ? y - x : null;
    const good = diff != null && (dir === "hi" ? diff > 1e-9 : diff < -1e-9), bad = diff != null && (dir === "hi" ? diff < -1e-9 : diff > 1e-9);
    return `<tr><td>${l}</td><td class="n">${fmt(x, d)}${x == null ? "" : u}</td><td class="n">${fmt(y, d)}${y == null ? "" : u}</td><td class="n ${good ? "good" : bad ? "bad" : "muted"}">${diff == null || Math.abs(diff) < 1e-9 ? "same" : (diff > 0 ? "+" : "") + fmt(diff, d)}</td><td class="muted">${alg}</td></tr>`;
  }).join("");
  // coverage is undefined while nobody is displaced, so leave those steps blank instead of plotting 100%
  const val = (s, key, mult) => (key === "covered_pct" && !s.m.displaced ? null : s.m[key] * mult);
  const ts = (key, mult = 1) => [{ y: B.map((s) => val(s, key, mult)), color: "#94a3b8", label: "2024-style" }, { y: A.map((s) => val(s, key, mult)), color: "#a78bfa", label: "AI", width: 2.3 }];
  const vl = [{ x: SIM.hours[step], color: "#64748b", dash: "3 3" }];
  return `
  <div class="kicker">Step 7 · Results</div><h1>Same storm, two responses</h1>
  <p class="lede">Both policies face identical closures, demand and bus fleet. Only the decisions differ. The table shows which algorithm is responsible for each difference.</p>
  <div class="ctrl"><span class="hint">Map shows</span><span class="seg" id="resSeg"><button data-v="ai" class="${resPolicy === "ai" ? "on" : ""}">AI response</button><button data-v="baseline" class="${resPolicy === "baseline" ? "on" : ""}">2024-style</button></span></div>
  <table class="t box"><tr><th>whole day</th><th class="n">2024-style</th><th class="n">AI</th><th class="n">change</th><th>driven by</th></tr>${tr}</table>
  ${RES && RES.available ? (() => {
    const sc = SIM.scenario;
    const keys = [["gave_up", "People who gave up", 0, ""], ["waiting_person_hours", "Hours queuing", 0, ""], ["worst_station_waiting", "Peak queue (worst station)", 0, ""],
      ["avg_extra_min", "Avg extra trip time", 1, " min"], ["p95_extra_min", "95th pct extra time", 1, " min"], ["covered_pct", "Within 10 min of relief", 1, "%"],
      ["unserved_pct", "Unserved", 2, "%"], ["staffed_critical_pct", "Critical stations staffed", 1, "%"], ["peak_ratio", "Peak crowding ratio", 2, "×"]];
    const rows = keys.map(([m, l, d, u]) => {
      const r = cmpRow(m, sc);
      if (!r) return "";
      const good = r.better_if === "lower" ? r.diff_mean < -1e-9 : r.diff_mean > 1e-9, bad = r.better_if === "lower" ? r.diff_mean > 1e-9 : r.diff_mean < -1e-9;
      return `<tr><td>${l}</td><td class="n">${pmf(r.baseline_mean, r.baseline_std, d)}${u}</td><td class="n">${pmf(r.ai_mean, r.ai_std, d)}${u}</td><td class="n ${good ? "good" : bad ? "bad" : "muted"}">${r.diff_mean > 0 ? "+" : ""}${pmf(r.diff_mean, null, d)}</td><td class="n">${r.ai_better_seeds}/${r.n}</td></tr>`;
    }).join("");
    return rows ? `<h2>Across 30 runs: ${sc.replace(/_/g, " ")} (mean ± std)</h2><table class="t box"><tr><th>metric</th><th class="n">2024-style</th><th class="n">AI</th><th class="n">diff</th><th class="n">AI better</th></tr>${rows}</table>` : "";
  })() : ""}
  <h2>Share of displaced passengers within 10 min of help</h2>
  ${Charts.line({ x: SIM.hours, series: ts("covered_pct"), vlines: vl, xFmt: hhmm, yMin: 0, yMax: 100, h: 150 })}
  <h2>Most crowded station (load ÷ capacity)</h2>
  ${Charts.line({ x: SIM.hours, series: ts("peak_ratio", 100), hlines: [{ y: 100, color: "#ef4444", label: "capacity" }], vlines: vl, xFmt: hhmm, yMin: 0, h: 150, yFmt: (v) => v.toFixed(0) + "%" })}
  <h2>Displaced passengers per 15 min</h2>
  ${Charts.line({ x: SIM.hours, series: [{ y: A.map((s) => s.m.displaced), color: "#38bdf8", label: "displaced (same for both)" }], vlines: vl, xFmt: hhmm, yMin: 0, h: 120 })}
  <h2>Honest reading</h2>
  <p>The AI's gains are in <b>getting people to help</b> and <b>spreading crowds</b>. Crowd-aware routing deliberately accepts slightly longer trips to avoid dangerous overcrowding, so average travel time can be equal or a few minutes worse. The charts above are this run (seed ${SIM.seed}); the table above them is the mean ± std over 30 runs (results/comparison.csv).</p>`;
}

/* ================================================================ wiring */
const TABS = {
  data: { layers: dataLayers, panel: dataPanel, timeline: false },
  flood: { layers: floodLayers, panel: floodPanel, timeline: true },
  fuzzy: { layers: fuzzyLayers, panel: fuzzyPanel, timeline: true },
  search: { layers: searchLayers, panel: searchPanel, timeline: false },
  bridge: { layers: bridgeLayers, panel: bridgePanel, timeline: false },
  ga: { layers: gaLayers, panel: gaPanel, timeline: false },
  results: { layers: resultsLayers, panel: resultsPanel, timeline: true },
};

function renderMap() { if (NET && SIM) overlay.setProps({ layers: TABS[tab].layers() }); }
let panelSeq = 0;
async function renderPanel() {
  if (!NET || !SIM) return;
  const seq = ++panelSeq;
  const html = await TABS[tab].panel();
  if (html == null || seq !== panelSeq) return;
  const ex = $("explain"), top = ex.scrollTop;
  ex.innerHTML = html;
  ex.scrollTop = top;
  bindPanel();
}
function refresh() { renderMap(); renderPanel(); }

function bindPanel() {
  const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };
  on("sOrig", "change", async () => { await loadSearch($("sOrig").value, $("sDest").value); refresh(); });
  on("sDest", "change", async () => { await loadSearch($("sOrig").value, $("sDest").value); refresh(); });
  on("sK", "input", () => { searchK = +$("sK").value; searchAnim = false; renderMap(); renderPanel(); });
  on("sPlay", "click", () => { if (searchK >= Math.max(SEARCH.astar.trace.length, SEARCH.dijkstra.trace.length)) searchK = 0; searchAnim = !searchAnim; renderPanel(); });
  document.querySelectorAll("#sMode button").forEach((b) => b.addEventListener("click", () => { searchMode = b.dataset.v; refresh(); }));
  document.querySelectorAll("#gaSeg button").forEach((b) => b.addEventListener("click", () => { gaShow = b.dataset.v; refresh(); }));
  document.querySelectorAll("#resSeg button").forEach((b) => b.addEventListener("click", () => { resPolicy = b.dataset.v; refresh(); }));
}

function setTab(t) {
  tab = t;
  sel = null;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $("timeline").classList.toggle("hidden", !TABS[t].timeline);
  $("tooltip").style.display = "none";
  $("explain").scrollTop = 0;
  if (t === "search" && !SEARCH && SIM && SIM.search) loadSearch(SIM.search.origin, SIM.search.dest).then(refresh);
  try { history.replaceState(null, "", "#" + t); } catch (e) { /* ignore */ }
  refresh();
}
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));

function setStep(s) {
  step = Math.max(0, Math.min(SIM.hours.length - 1, s));
  $("scrub").value = step;
  $("tlabel").textContent = `${hhmm(SIM.hours[step])} · rain ${fmt(SIM.storm_track[step][2])} mm/h`;
  if (TABS[tab].timeline) refresh();
}
$("scrub").addEventListener("input", () => { playing = false; $("playBtn").textContent = "▶"; stepF = +$("scrub").value; setStep(stepF); });
$("playBtn").addEventListener("click", () => {
  playing = !playing;
  $("playBtn").textContent = playing ? "❚❚" : "▶";
  if (playing && step >= SIM.hours.length - 1) stepF = 0;
});
document.addEventListener("keydown", (e) => {
  if (["INPUT", "SELECT"].includes(e.target.tagName)) return;
  if (e.key === " ") { e.preventDefault(); $("playBtn").click(); }
  if (e.key === "ArrowRight") { stepF = step + 1; setStep(step + 1); }
  if (e.key === "ArrowLeft") { stepF = step - 1; setStep(step - 1); }
  const n = +e.key;
  if (n >= 1 && n <= 7) setTab(Object.keys(TABS)[n - 1]);
});

let last = performance.now(), acc = 0;
function frame(now) {
  const dt = now - last; last = now;
  if (SIM && playing && TABS[tab].timeline) {
    stepF += (dt / 1000) * 3; // 3 steps (45 simulated minutes) per second
    if (stepF >= SIM.hours.length - 1) { stepF = SIM.hours.length - 1; playing = false; $("playBtn").textContent = "▶"; }
    if (Math.floor(stepF) !== step) setStep(Math.floor(stepF));
  }
  if (tab === "search" && searchAnim && SEARCH) {
    acc += dt;
    if (acc > 140) {
      acc = 0;
      const maxK = Math.max(SEARCH.astar.trace.length, SEARCH.dijkstra.trace.length);
      searchK = Math.min(maxK, searchK + 1);
      if (searchK >= maxK) searchAnim = false;
      renderMap();
      renderPanel();
    }
  }
  requestAnimationFrame(frame);
}

async function runSim() {
  $("runBtn").disabled = true;
  $("status").textContent = "Running flood model, fuzzy priority, A* routing and the GA…";
  const t0 = performance.now();
  try {
    const r = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: $("scenario").value, seed: +$("seed").value }) });
    if (!r.ok) throw new Error(await r.text());
    SIM = await r.json();
    SEARCH = null; fuzzyCache.clear();
    $("scrub").max = SIM.hours.length - 1;
    $("status").textContent = `${((performance.now() - t0) / 1000).toFixed(1)} s · ${SIM.closed_final.length} closed`;
    // start the timeline at the moment the first station closes (most informative), or mid-storm
    const firstClose = Math.min(...SIM.closed_at.filter((c) => c >= 0));
    stepF = Number.isFinite(firstClose) ? Math.min(SIM.hours.length - 1, firstClose + 2) : Math.floor(SIM.hours.length / 2);
    setStep(Math.floor(stepF));
    if (tab === "search" && SIM.search) await loadSearch(SIM.search.origin, SIM.search.dest);
    refresh();
  } catch (e) {
    $("status").textContent = "Error: " + e.message.slice(0, 120);
  } finally {
    $("runBtn").disabled = false;
  }
}
$("runBtn").addEventListener("click", runSim);
$("scenario").addEventListener("change", runSim);

async function init() {
  NET = await (await fetch("/api/network")).json();
  try { RES = await (await fetch("/api/results")).json(); } catch (e) { RES = null; }
  NET.stations.forEach((s, i) => (IDX[s.name] = i));
  const start = (location.hash || "#data").slice(1);
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === start));
  tab = TABS[start] ? start : "data";
  requestAnimationFrame(frame);
  await runSim();
  setTab(tab);
}
init();
