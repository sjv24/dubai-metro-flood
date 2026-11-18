/* Story mode: 16 April 2024 → why it went wrong → the AI's decisions (A*, fuzzy logic, GA) → rerun with AI → compare.
   Every number shown comes from the backend run of the April 2024 replay (seed 42). */
const { MapboxOverlay, PathLayer, ColumnLayer, ScatterplotLayer, TextLayer, LineLayer, TripsLayer } = deck;

const STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const LINE_RGB = { Red: [229, 72, 72], Green: [52, 178, 90] };
const CAM = {
  far: { center: [55.18, 25.12], zoom: 9.2, pitch: 0, bearing: 0 },
  city: { center: [55.235, 25.15], zoom: 10.5, pitch: 48, bearing: -28 },
  focus: { center: [55.235, 25.175], zoom: 11.35, pitch: 56, bearing: -38 },
  flat: { center: [55.225, 25.16], zoom: 11.0, pitch: 20, bearing: -20 },
  split: { center: [55.24, 25.17], zoom: 10.9, pitch: 52, bearing: -36 },
};
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => (n == null || Number.isNaN(n) ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const hhmm = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
const combWords = (n, k) => { let r = 1; for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i; return r >= 1e9 ? `${(r / 1e9).toFixed(1)} billion` : r >= 1e6 ? `${(r / 1e6).toFixed(1)} million` : fmt(r); };
const pct = (a, b) => (b ? Math.round((100 * (a - b)) / b) : 0);

let NET, SIM, SEARCH, FUZ, EXT = null, RES = null, IDX = {};
let ch = 0, step = 0, stepF = 0, playing = false, playTo = null, anim = 0, animStart = 0;
const views = [];

/* ================================================================ data helpers */
const S = (name) => NET.stations[IDX[name]];
const short = (n) => { const s = S(n); return s ? s.display.replace(/ \(.*\)$/, "").replace("Burj Khalifa/ Dubai Mall", "Burj Khalifa") : n; };
const stepOf = (h) => Math.max(0, Math.min(SIM.hours.length - 1, Math.round((h - SIM.hours[0]) / 0.25)));
const isClosed = (i, t = step) => SIM.closed_at[i] >= 0 && SIM.closed_at[i] <= t;
function stateAt(t) { let c = null; for (const s of SIM.states) if (s.from_step <= t && (!c || s.from_step >= c.from_step)) c = s; return c; }
const finalState = () => [...SIM.states].reverse().find((s) => s.ga);
function ramp(t, stops) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < stops.length; i++) if (t <= stops[i][0]) {
    const [a, ca] = stops[i - 1], [b, cb] = stops[i], u = (t - a) / (b - a || 1);
    return [0, 1, 2].map((k) => Math.round(ca[k] + (cb[k] - ca[k]) * u));
  }
  return stops[stops.length - 1][1];
}
const crowdRGB = (r) => ramp(r / 2.5, [[0, [34, 197, 94]], [0.3, [132, 204, 22]], [0.4, [234, 179, 8]], [0.55, [249, 115, 22]], [0.75, [239, 68, 68]], [1, [190, 18, 60]]]);
const prioRGB = (p) => ramp(p / 100, [[0, [34, 197, 94]], [0.35, [234, 179, 8]], [0.6, [249, 115, 22]], [0.85, [239, 68, 68]], [1, [239, 68, 68]]]);
function offsetRing(lat, lon, km, n) {
  const out = [];
  for (let i = 0; i < n; i++) { const a = (i / n) * 2 * Math.PI; out.push([lon + (km / (111 * Math.cos((lat * Math.PI) / 180))) * Math.cos(a), lat + (km / 111) * Math.sin(a)]); }
  return out;
}

/* ================================================================ multi-seed statistics */
const cmpRow = (metric, scenario = "april_2024_replay") => (RES && RES.comparison ? RES.comparison.find((r) => r.scenario === scenario && r.metric === metric) : null);
const pm = (m, s, d = 0) => (m == null ? "–" : `${fmt(m, d)}${s == null ? "" : ` ± ${fmt(s, d)}`}`);
const gaRow = (method, scenario = "april_2024_replay") => (RES && RES.ga ? RES.ga.find((r) => r.scenario === scenario && r.method === method) : null);
const searchRow = (measure, alg) => (RES && RES.search ? RES.search.find((r) => r.measure.startsWith(measure) && (!alg || r.algorithm === alg)) : null);

/* ================================================================ map views */
function makeView(id, canvas) {
  const map = new maplibregl.Map({ container: id, style: STYLE, ...CAM.far, attributionControl: { compact: true } });
  const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
  map.addControl(overlay);
  const c = $(canvas);
  return { map, overlay, canvas: c, ctx: c.getContext("2d"), drops: [], policy: "baseline", mode: "plain" };
}
function syncCams() {
  let lock = false;
  const [a, b] = views;
  const s = (x, y) => () => { if (lock || !document.body.classList.contains("split")) return; lock = true; y.map.jumpTo({ center: x.map.getCenter(), zoom: x.map.getZoom(), pitch: x.map.getPitch(), bearing: x.map.getBearing() }); lock = false; };
  a.map.on("move", s(a, b)); b.map.on("move", s(b, a));
}

/* ================================================================ layers */
const tracks = (a = 230) => [
  new PathLayer({ id: "glow", data: NET.track_parts, getPath: (d) => d.path, getColor: (d) => [...LINE_RGB[d.line], Math.round(a * 0.18)], getWidth: 9, widthUnits: "pixels", capRounded: true, jointRounded: true }),
  new PathLayer({ id: "trk", data: NET.track_parts, getPath: (d) => d.path, getColor: (d) => [...LINE_RGB[d.line], a], getWidth: 2.2, widthUnits: "pixels", capRounded: true, jointRounded: true }),
];
const text = (id, items, size = 12.5, color = [241, 245, 249]) => new TextLayer({
  id, data: items, getPosition: (d) => d.p, getText: (d) => d.t, getSize: (d) => d.s || size, getColor: (d) => d.c || color, getPixelOffset: (d) => d.o || [0, -18],
  fontFamily: "Inter, sans-serif", fontWeight: 700, outlineWidth: 3, outlineColor: [6, 8, 12, 240], fontSettings: { sdf: true }, characterSet: "auto", billboard: true,
});
function closedLayers(t, now) {
  const list = NET.stations.filter((s, i) => isClosed(i, t));
  const ph = (now % 1800) / 1800;
  return [
    new ScatterplotLayer({ id: "cp", data: list, getPosition: (s) => [s.lon, s.lat], getRadius: 250 + 500 * ph, filled: false, stroked: true, getLineColor: [226, 232, 240, 200 * (1 - ph)], lineWidthMinPixels: 2, updateTriggers: { getRadius: ph, getLineColor: ph } }),
    text("cx", list.map((s) => ({ p: [s.lon, s.lat, 80], t: "✕", o: [0, 0], s: 17 }))),
  ];
}
function floodLayer(t) {
  const thr = NET.threshold_mm, pts = [];
  NET.stations.forEach((s, i) => {
    const w = Math.min(SIM.water[t][i] / thr, 1.6);
    if (w <= 0.03) return;
    for (let k = 0; k < 3; k++) pts.push({ p: [s.lon, s.lat], r: (280 + 650 * w) * (1 - k * 0.22), a: 22 + 26 * Math.min(w, 1) });
    for (const q of offsetRing(s.lat, s.lon, 0.3 + 0.4 * w, 6)) pts.push({ p: q, r: 200 + 280 * w, a: 16 + 18 * Math.min(w, 1) });
  });
  return new ScatterplotLayer({ id: "flood", data: pts, getPosition: (d) => d.p, getRadius: (d) => d.r, getFillColor: (d) => [14, 165, 233, d.a], parameters: { depthTest: false } });
}
function stormLayer(t) {
  const [lon, lat, I] = SIM.storm_track[t];
  if (I <= 0) return [];
  const r = SIM.storm.radius_km * 1000;
  return [new ScatterplotLayer({ id: "storm", data: [1, 0.6], getPosition: () => [lon, lat], getRadius: (k) => r * k, getFillColor: (k) => [148, 163, 184, Math.min(40, 6 + I * 0.6) * (k < 1 ? 1.4 : 1)], parameters: { depthTest: false } })];
}
let MAXPEOPLE = 1;
function crowdColumns(pol, t, colorBy = "crowd") {
  const st = SIM.steps[pol][t];
  const data = NET.stations.map((s, i) => ({ s, i, closed: isClosed(i, t) }));
  return new ColumnLayer({
    id: "cols-" + pol, data, diskResolution: 18, radius: 210, extruded: true,
    getPosition: (d) => [d.s.lon, d.s.lat],
    getElevation: (d) => (d.closed ? 40 : 60 + ((st.load[d.i] + st.queue[d.i]) / MAXPEOPLE) * 7000),
    getFillColor: (d) => (d.closed ? [100, 116, 139, 220] : colorBy === "prio" ? [...prioRGB(st.priority[d.i]), 240] : [...crowdRGB(st.ratio[d.i]), 240]),
    updateTriggers: { getElevation: [t, pol], getFillColor: [t, pol, colorBy] },
  });
}
function busLayers(plan, now, color = [253, 224, 71]) {
  if (!plan) return [];
  if (!plan._trips) {
    const P = 9, trips = [];
    plan.routes.forEach((r) => {
      const loop = r.coords.concat(r.coords.slice(0, -1).reverse());
      const ts = [0];
      for (let i = 1; i < loop.length; i++) ts.push(ts[i - 1] + Math.hypot((loop[i][0] - loop[i - 1][0]) * 101, (loop[i][1] - loop[i - 1][1]) * 111) + 0.05);
      const L = ts[ts.length - 1], nb = Math.min(r.buses, 10);
      for (let b = 0; b < nb; b++) {
        const path = [], times = [];
        for (let c = 0; c < 3; c++) loop.forEach((p, i) => { path.push(p); times.push((ts[i] / L) * P + c * P - (b / nb) * P); });
        trips.push({ path, times, split: r.kind === "split" });
      }
    });
    plan._trips = trips;
  }
  return [
    new PathLayer({ id: "routes" + color, data: plan.routes, getPath: (r) => r.coords, getColor: (r) => (r.kind === "split" ? [196, 181, 253, 150] : [...color, 120]), getWidth: 3, widthUnits: "pixels", jointRounded: true }),
    new TripsLayer({ id: "buses" + color, data: plan._trips, getPath: (d) => d.path, getTimestamps: (d) => d.times, getColor: (d) => (d.split ? [196, 181, 253] : color),
      widthMinPixels: 6, capRounded: true, jointRounded: true, trailLength: 0.8, fadeTrail: true, currentTime: 9 + ((now / 1000) % 9) }),
  ];
}
function reliefLayer(plan, pol) {
  if (!plan) return [];
  const col = pol === "ai" ? [167, 139, 250] : [226, 232, 240];
  return [
    new ScatterplotLayer({ id: "relief" + pol, data: plan.relief, getPosition: (h) => [h.lon, h.lat], getRadius: 7, radiusUnits: "pixels", getFillColor: [...col, 255], stroked: true, getLineColor: [6, 8, 12, 255], lineWidthMinPixels: 2, parameters: { depthTest: false } }),
  ];
}
function worstLabel(pol, t) {
  const st = SIM.steps[pol][t];
  const items = [];
  st.queue.forEach((q, i) => { if (q > 300) items.push({ q, i }); });
  items.sort((a, b) => b.q - a.q);
  return text("worst" + pol, items.slice(0, 2).map(({ q, i }) => ({ p: [NET.stations[i].lon, NET.stations[i].lat, 60 + ((st.load[i] + q) / MAXPEOPLE) * 7000], t: `${short(NET.stations[i].name)} · ${fmt(q)} waiting`, c: [254, 202, 202], o: [0, -14] })), 13);
}

function simLayers(v, now) {
  const t = step, pol = v.policy, st = stateAt(t), plan = st && st[pol];
  return [...tracks(), floodLayer(t), ...stormLayer(t), ...busLayers(plan, now, pol === "ai" ? [253, 224, 71] : [253, 224, 71]),
    crowdColumns(pol, t), ...closedLayers(t, now), ...reliefLayer(plan, pol), worstLabel(pol, t)];
}

/* --- algorithm chapters --- */
function fuzzyLayers(v, now) {
  const t = PEAK, st = SIM.steps.baseline[t];
  const crit = NET.stations.map((s, i) => ({ s, i })).filter((d) => !isClosed(d.i, t) && st.priority[d.i] >= 80);
  const ph = (now % 1500) / 1500;
  return [...tracks(140), crowdColumns("baseline", t, "prio"), ...closedLayers(t, now),
    new ScatterplotLayer({ id: "crit", data: crit, getPosition: (d) => [d.s.lon, d.s.lat], getRadius: 450 + 900 * ph, filled: false, stroked: true, getLineColor: [239, 68, 68, 230 * (1 - ph)], lineWidthMinPixels: 2.5, updateTriggers: { getRadius: ph, getLineColor: ph } }),
    text("cl", crit.map((d) => ({ p: [d.s.lon, d.s.lat, 60 + ((st.load[d.i] + st.queue[d.i]) / MAXPEOPLE) * 7000], t: `${short(d.s.name)} · ${fmt(st.priority[d.i])}`, c: [254, 202, 202] })))];
}
function gaLayers(v, now) {
  const g = finalState().ga, fs = finalState();
  const gens = g.best_per_gen, k = Math.min(gens.length - 1, Math.floor(((now - animStart) / 6500) * gens.length));
  GA_GEN = k;
  const hubs = gens[k], done = k >= gens.length - 1;
  const hubPos = Object.fromEntries(g.hubs.map((h) => [h.name, [h.lon, h.lat]]));
  const links = done ? g.nearest_hub.filter((l) => hubPos[l.hub]).map((l) => ({ a: [S(l.station).lon, S(l.station).lat], b: hubPos[l.hub], m: l.minutes })) : [];
  return [...tracks(110), ...closedLayers(SIM.hours.length - 1, now),
    new ScatterplotLayer({ id: "cand", data: g.candidates, getPosition: (c) => [c.lon, c.lat], getRadius: 2.2, radiusUnits: "pixels", getFillColor: [148, 163, 184, 120] }),
    ...reliefLayer(fs.baseline, "baseline"),
    new LineLayer({ id: "links", data: links, getSourcePosition: (d) => d.a, getTargetPosition: (d) => d.b, getColor: [196, 181, 253, 220], getWidth: 2, widthUnits: "pixels" }),
    new ScatterplotLayer({ id: "gah", data: hubs, getPosition: (h) => [h.lon, h.lat], getRadius: 9, radiusUnits: "pixels", getFillColor: [167, 139, 250, 255], stroked: true, getLineColor: [255, 255, 255, 255], lineWidthMinPixels: 2, transitions: { getPosition: 220 } }),
    text("gal", done ? g.hubs.map((h) => ({ p: [h.lon, h.lat], t: h.name.length > 24 ? h.name.slice(0, 22) + "…" : h.name, c: [221, 214, 254] })) : [], 12),
    text("lm", links.map((l) => ({ p: [(l.a[0] + l.b[0]) / 2, (l.a[1] + l.b[1]) / 2], t: fmt(l.m, 1) + " min", o: [0, 0], c: [196, 181, 253] })), 11)];
}
let GA_GEN = 0, SEARCH_K = 0;
function searchLayers(v, now) {
  if (!SEARCH) return tracks();
  const A = SEARCH.astar, D = SEARCH.dijkstra, maxK = Math.max(A.trace.length, D.trace.length);
  const k = Math.min(maxK, Math.floor((now - animStart) / 150));
  SEARCH_K = k;
  const fs = finalState();
  const o = A.path[0], gl = A.path[A.path.length - 1];
  return [...tracks(110), ...closedLayers(SIM.hours.length - 1, now),
    new LineLayer({ id: "walk", data: SEARCH.graph.filter((e) => e.mode === "walk"), getSourcePosition: (d) => d.a, getTargetPosition: (d) => d.b, getColor: [100, 116, 139, 90], getWidth: 1, widthUnits: "pixels" }),
    new PathLayer({ id: "br", data: fs.baseline.routes, getPath: (r) => r.coords, getColor: [253, 224, 71, 140], getWidth: 2.5, widthUnits: "pixels" }),
    new ScatterplotLayer({ id: "dij", data: D.trace.slice(0, k), getPosition: (t) => [t.lon, t.lat], getRadius: 10, radiusUnits: "pixels", filled: false, stroked: true, getLineColor: [232, 121, 249, 230], lineWidthMinPixels: 2 }),
    new ScatterplotLayer({ id: "ast", data: A.trace.slice(0, k), getPosition: (t) => [t.lon, t.lat], getRadius: 5, radiusUnits: "pixels", getFillColor: [34, 211, 238, 255] }),
    ...(k >= maxK ? [new PathLayer({ id: "path", data: [A.path.map((p) => [p.lon, p.lat])], getPath: (d) => d, getColor: [255, 255, 255, 245], getWidth: 4.5, widthUnits: "pixels", capRounded: true, jointRounded: true })] : []),
    text("od", [{ p: [o.lon, o.lat], t: "START · " + short(SEARCH.origin) }, { p: [gl.lon, gl.lat], t: "GOAL · " + short(SEARCH.dest) }], 13)];
}
function bridgeLayers(v, now) {
  const fs = finalState();
  const t = PEAK;
  return [...tracks(120), ...closedLayers(SIM.hours.length - 1, now),
    new PathLayer({ id: "b24", data: fs.baseline.routes, getPath: (r) => r.coords, getColor: [148, 163, 184, 160], getWidth: 10, widthUnits: "pixels", capRounded: true, jointRounded: true }),
    ...busLayers(fs.ai, now, [253, 224, 71]),
    text("bt", [...new Set(fs.ai.routes.flatMap((r) => [r.stops[0], r.stops[r.stops.length - 1]]))].filter((n) => !fs.displaced.includes(n)).map((n) => ({ p: [S(n).lon, S(n).lat], t: short(n) })), 12.5)];
}
function plainLayers(v, now) { return [...tracks(), ...closedLayers(PEAK, now)]; }

/* ================================================================ HUD */
function hud(el, pol) {
  const m = SIM.steps[pol][step].m;
  el.innerHTML = `<div class="t"><b>${hhmm(SIM.hours[step])}</b><span>rain ${fmt(SIM.storm_track[step][2])} mm/h</span></div>
    <div class="row"><span>Stations closed</span><span>${m.closed}</span></div>
    <div class="row"><span>Stranded so far</span><span>${fmt(m.stranded_so_far)}</span></div>
    <div class="row red"><span>Waiting on platforms now</span><span>${fmt(m.waiting)}</span></div>
    <div class="row amber"><span>Stations over capacity</span><span>${m.overloaded}</span></div>
    <div class="row red"><span>Gave up on the metro</span><span>${fmt(m.gave_up_so_far)}</span></div>
    ${m.displaced ? `<div class="row violet"><span>Reach help ≤ 10 min</span><span>${fmt(m.covered_pct)}%</span></div>` : ""}`;
}

/* ================================================================ chapters */
let PEAK = 0;
const legendCrowd = `<div><span class="ramp" style="background:linear-gradient(90deg,#22c55e,#eab308,#f97316,#ef4444,#be123c)"></span>Crowding (people ÷ capacity)</div><div><span class="sw" style="background:#94a3b8"></span>Column height = people at the station</div><div><span class="sw" style="background:#0ea5e9"></span>Flood water</div><div><span class="ln" style="background:#fde047"></span>Replacement shuttle bus</div>`;
const legendRelief = (pol) => `<div><span class="sw" style="background:${pol === "ai" ? "#a78bfa" : "#e2e8f0"}"></span>${pol === "ai" ? "AI relief hubs" : "Help points (shuttle ends only)"}</div>`;

const CHAPTERS = [
  {
    id: "cover", cam: "far", mode: "cover", clock: false,
    html: () => `<div class="kicker red">16 April 2024 · Dubai</div><h1 class="huge">The day the metro flooded</h1>
      <p class="lead">The UAE recorded its heaviest rainfall since records began in 1949: <b>254 mm in 24 hours</b> in Al Ain.</p>
      <div class="facts"><div class="fact red"><div class="v">4</div><div class="k">Red Line stations shut: Onpassive, Equiti, Mashreq, Energy</div></div>
      <div class="fact red"><div class="v">5–6 wks</div><div class="k">until they reopened (19 and 28 May)</div></div></div>
      <p>The Red Line ran in two halves, with shuttle buses between <b>Business Bay</b> and <b>Al Khail</b>. Passengers were asked to avoid the metro at peak hours.</p>
      <p>We rebuilt that day on <b>real RTA open data</b>, then asked: <b>could an AI have handled it better?</b></p>
      <button class="cta" onclick="go(1)">Replay 16 April 2024 ▶</button>
      <p class="hint" style="margin-top:12px">Sources: The National (23 Apr, 8 May, 19 May 2024), Khaleej Times.</p>`,
  },
  {
    id: "storm", cam: "city", mode: "sim", policy: "baseline", hud: true, play: [5.0, 12.5], legend: () => legendCrowd,
    html: () => `<div class="kicker red">Act 1 · What happened</div><h1>The storm moves in</h1>
      <p class="lead">Each column is a real metro station. Its height is the number of people there right now: typical 2025 RTA ridership, spread over the day.</p>
      <p>The storm cell drifts across the city. Water builds up around stations (blue). When it passes <b>${NET.threshold_mm} mm</b>, a station floods and closes (✕).</p>
      <div class="box"><b>The real closures.</b> The replay closes exactly the four stations that closed in 2024: Onpassive, Equiti, Mashreq and Energy. The storm model only decides <b>when</b>. In April 2024 their ridership fell to <b>34–55%</b> of March, against <b>71%</b> network-wide. We use that drop as each station's flood vulnerability.${RES && RES.calibration ? ` <span class="hint">Validation: the flood model on its own picks ${fmt(100 * RES.calibration.recall_mean)}% of the real closures with ${fmt(100 * RES.calibration.precision_mean)}% precision over ${RES.calibration.seeds} runs (it misses Energy).</span>` : ""}</div>
      <p class="hint">Watch the counters on the right.</p>`,
  },
  {
    id: "pileup", cam: "focus", mode: "sim", policy: "baseline", hud: true, play: [12.5, 21.5], legend: () => legendCrowd + legendRelief("baseline"),
    html: () => {
      const st = finalState();
      const r = st.baseline.routes[0];
      return `<div class="kicker red">Act 1 · The 2024-style response</div><h1>Then the crowds pile up</h1>
      <p class="lead">With ${short(r.stops[1])}, ${short(r.stops[2])} and ${short(r.stops[4])} closed, ${short(r.stops[3])} is cut off too.${st.breaks.length > 1 ? ` Later Energy closes, cutting off ${st.breaks[1].closed.filter((n) => n !== "Energy").map(short).join(" and ")}.` : ""} <b>${fmt(SIM.steps.baseline[stepOf(17.5)].m.displaced)} people every 15 minutes</b> need another way.</p>
      <p>The response we model on 2024:</p>
      <ul><li><b>One shuttle</b> between the stations either side: ${short(r.stops[0])} ⇄ ${short(r.stops[r.stops.length - 1])}</li>
      <li><b>Help only at its two ends</b></li><li><b>Everyone takes the quickest route</b>, so most end up at ${short(r.stops[0])}</li><li>Staff sent in line order</li></ul>
      <p>Watch <b>${short(SIM.summary.baseline.worst_station)}</b> as the evening peak hits. People who can't board wait for the next train, and the column keeps growing.</p>`;
    },
  },
  {
    id: "damage", cam: "focus", mode: "sim", policy: "baseline", hud: true, freeze: () => PEAK, legend: () => legendCrowd,
    html: () => {
      const b = SIM.summary.baseline;
      return `<div class="kicker red">Act 1 · The cost</div><h1>By the end of the day</h1>
      <div class="facts">
        <div class="fact red"><div class="v">${fmt(b.gave_up)}</div><div class="k">people gave up on the metro (taxi, walk, cancelled)</div></div>
        <div class="fact red"><div class="v">${fmt(b.worst_station_waiting)}</div><div class="k">people queuing at ${short(b.worst_station)} at ${hhmm(b.peak_waiting_time)}</div></div>
        <div class="fact red"><div class="v">${fmt(b.waiting_person_hours)} h</div><div class="k">spent waiting on platforms</div></div>
        <div class="fact red"><div class="v">${fmt(b.covered_pct)}%</div><div class="k">of stranded people reached help within 10 minutes</div></div>
      </div>
      <p>Stranded passengers lost an average of <b>${fmt(b.avg_extra_min)} extra minutes</b> per trip (1 in 20 lost over ${fmt(b.p95_extra_min)}).</p>
      <p class="hint">Modelled, not measured: a simulation of the 2024-style response on real network and ridership data.</p>`;
    },
  },
  {
    id: "decisions", cam: "flat", mode: "plain", clock: false, wide: true,
    html: () => `<div class="kicker">Act 2 · How could we do better?</div><h1>Four decisions, three AI techniques</h1>
      <p class="lead">Every disruption forces the same four decisions, fast. Our AI makes them with three techniques: <b>fuzzy logic</b>, a <b>genetic algorithm</b> and <b>A* search</b>.</p>
      <ul class="decisions">
        <li><span class="n">1</span><div><div class="q">Which stations need help first?</div><div class="a">Crowding, flooding, interchanges and closures all matter, and they're vague. → <span class="alg">Fuzzy logic</span></div></div></li>
        <li><span class="n">2</span><div><div class="q">Where do we set up relief hubs?</div><div class="a">5 sites out of ${finalState().ga.n_candidates} candidates is ${combWords(finalState().ga.n_candidates, 5)} combinations. → <span class="alg">Genetic algorithm</span></div></div></li>
        <li><span class="n">3</span><div><div class="q">How should stranded passengers travel?</div><div class="a">The fastest route around the closure that also avoids crowds. → <span class="alg">A* search</span></div></div></li>
        <li><span class="n">4</span><div><div class="q">Where should replacement buses run?</div><div class="a">Score every candidate bus design by routing all passengers on it. → <span class="alg">evaluated with A*</span></div></div></li>
      </ul>`,
  },
  {
    id: "fuzzy", cam: "focus", mode: "fuzzy", clock: false,
    legend: () => `<div><span class="ramp" style="background:linear-gradient(90deg,#22c55e,#eab308,#f97316,#ef4444)"></span>Fuzzy priority 0 → 100</div><div><span class="sw" style="border:2px solid #ef4444"></span>Critical (≥ 80): send staff here</div>`,
    html: () => {
      const bb = IDX[SIM.summary.baseline.worst_station], st = SIM.steps.baseline[PEAK];
      const inp = FUZ ? FUZ.inputs : null, fired = FUZ ? FUZ.rules.filter((r) => r.strength > 0).sort((a, b) => b.strength - a.strength) : [];
      const deg = (v) => (FUZ ? Object.entries(FUZ.degrees[v]).filter(([, d]) => d > 0).map(([t, d]) => `${t} ${fmt(d, 2)}`).join(", ") : "");
      const nCrit = st.priority.filter((p, i) => p >= 80 && !isClosed(i, PEAK)).length;
      return `<div class="kicker violet">Decision 1 · Fuzzy logic</div><h1>Who needs help first?</h1>
      <p class="lead">Humans say "very crowded" or "right next to a closure". Fuzzy logic turns those vague words into <b>one priority score, 0–100</b>, for every station, every 15 minutes.</p>
      ${FUZ ? `<div class="formula">${short(NET.stations[bb].name)} at ${hhmm(SIM.hours[PEAK])}:
crowding  = <span class="v">${fmt(inp.load, 2)}</span> × capacity  → ${deg("load")}
flood     = <span class="v">${fmt(inp.flood, 2)}</span> of threshold → ${deg("flood")}
closure   = <span class="v">${fmt(inp.dist)}</span> stop away      → ${deg("dist")}

rule ${fired[0].id}: IF ${fired[0].if.map((c) => `${c.var} is ${c.term}`).join(" AND ")}
        THEN ${fired[0].then}   (strength ${fmt(fired[0].strength, 2)})

centroid of the output → <span class="r">${fmt(FUZ.centroid)} = ${FUZ.label}</span></div>` : ""}
      <p>17 rules like this, each firing as strongly as its weakest condition (min), are combined (max), and the centre of mass gives the score. Right now <b>${nCrit} station${nCrit === 1 ? " is" : "s are"} Critical</b> (red rings).</p>
      <p>The AI sends its <b>6 staff teams to the highest scores</b>. The 2024-style response sends them in line order.${cmpRow("staffed_critical_pct") ? ` Across ${cmpRow("staffed_critical_pct").n} runs, critical stations staffed: <b>${pm(cmpRow("staffed_critical_pct").baseline_mean, cmpRow("staffed_critical_pct").baseline_std)}%</b> → <b>${pm(cmpRow("staffed_critical_pct").ai_mean, cmpRow("staffed_critical_pct").ai_std)}%</b>.` : ""}</p>
      <a class="deep" href="/explorer#fuzzy" target="_blank">See every membership function and rule ↗</a>`;
    },
  },
  {
    id: "hubs", cam: "flat", mode: "ga", clock: false, anim: true,
    legend: () => `<div><span class="sw" style="background:#94a3b8"></span>Candidate sites (stations + real bus stops)</div><div><span class="sw" style="background:#e2e8f0"></span>2024: help at shuttle ends only</div><div><span class="sw" style="background:#a78bfa"></span>GA hubs (best chromosome)</div>`,
    html: () => {
      const g = finalState().ga, b = SIM.summary.baseline, a = SIM.summary.ai;
      return `<div class="kicker violet">Decision 2 · Genetic algorithm</div><h1>Where do we set up relief hubs?</h1>
      <p class="lead">A <b>relief hub</b> is a staffed point outside the station: marshals, water and first aid, live travel information and app alerts, and a taxi and bus rank.</p>
      <p>Choosing <b>5</b> of <b>${g.n_candidates}</b> candidate sites gives <b>${combWords(g.n_candidates, 5)}</b> combinations. The GA evolves them instead:</p>
      <div class="formula">chromosome = 5 sites   (population ${g.params.population})
fitness = people reaching a hub ≤ 10 min
        + urgent (fuzzy) stations covered
        − crowded hubs − distance
evolve  = select → crossover → mutate → keep best</div>
      <div class="box"><b id="gaGen">Generation 0</b> · best fitness <b id="gaFit">${fmt(g.curve_best[0], 3)}</b><div id="gaChart"></div></div>
      <div class="vs"><div class="l">${fmt(b.covered_pct)}%</div><div class="m">stranded people within<br>10 min of help</div><div class="r">${fmt(a.covered_pct)}%</div></div>
      <p class="hint">Left: 2024-style (help only at the shuttle ends). Right: GA hubs.</p>
      ${gaRow("ga") ? `<div class="box"><b>Across ${gaRow("ga").n} runs</b> (fitness, mean ± std): GA <b>${pm(gaRow("ga").fitness_mean, gaRow("ga").fitness_std, 3)}</b> · greedy ${pm(gaRow("greedy").fitness_mean, gaRow("greedy").fitness_std, 3)} · random ${pm(gaRow("random").fitness_mean, gaRow("random").fitness_std, 3)}. GA ≥ greedy in <b>${fmt(gaRow("GA >= greedy (seeds)").fitness_mean)}/${gaRow("ga").n}</b> runs: close to greedy, far above random.</div>` : `<p class="hint">This run: GA ${fmt(g.fitness, 3)} · greedy ${fmt(g.greedy, 3)} · random ${fmt(g.random, 3)}.</p>`}
      <a class="deep" href="/explorer#ga" target="_blank">Fitness breakdown and operators ↗</a>`;
    },
  },
  {
    id: "astar", cam: "flat", mode: "search", clock: false, anim: true,
    legend: () => `<div><span class="sw" style="border:2px solid #e879f9"></span>Dijkstra: places checked</div><div><span class="sw" style="background:#22d3ee"></span>A*: places checked</div><div><span class="ln" style="background:#fff"></span>Fastest route (same for both)</div>`,
    html: () => {
      if (!SEARCH) return `<h1>Loading search…</h1>`;
      const A = SEARCH.astar, D = SEARCH.dijkstra;
      return `<div class="kicker violet">Decision 3 · A* search</div><h1>How should stranded passengers travel?</h1>
      <p class="lead">Every stranded trip needs a new route around the closure: trains, walking and shuttle buses, on a graph of ${SEARCH.nodes} nodes.</p>
      <div class="formula">Dijkstra: explore by g(n)          (time so far)
A*:       explore by g(n) + h(n)
          h = straight-line time to goal
h never overestimates ⇒ optimal route</div>
      <div class="vs"><div class="l" style="color:#f0abfc">${D.expanded}</div><div class="m">places checked<br>${short(SEARCH.origin)} → ${short(SEARCH.dest)}</div><div class="r" style="color:#67e8f9">${A.expanded}</div></div>
      <p>Same <b>${fmt(A.cost, 1)}-minute</b> route, <b>${fmt(100 * (1 - A.expanded / D.expanded))}% less work</b>. Dijkstra (pink) wastes time exploring south, away from the goal. A* (blue) heads straight there. Across thousands of trips every 15 minutes, that matters.</p>
      ${searchRow("Nodes expanded", "A*") ? `<div class="box"><b>Over ${fmt(searchRow("Trips with identical").mean)} random trips</b> on the disrupted network: A* expands <b>${fmt(searchRow("Nodes expanded", "A*").mean, 1)}</b> nodes on average vs Dijkstra's <b>${fmt(searchRow("Nodes expanded", "Dijkstra").mean, 1)}</b> (${fmt(searchRow("A* expansion saving").mean)}% ± ${fmt(searchRow("A* expansion saving").std)}% less), with an identical optimal cost on every trip. On a network this small, the wall-clock times are similar (${fmt(searchRow("Runtime", "A*").mean, 3)} vs ${fmt(searchRow("Runtime", "Dijkstra").mean, 3)} ms), because computing h costs about as much as the expansions it saves.</div>` : ""}
      <div class="box"><b>Crowd-aware.</b> The AI's A* also adds the expected queue at each boarding station (15 min × how far over capacity it is). It sends some passengers to a less crowded station instead of everyone to the nearest one.</div>
      <a class="deep" href="/explorer#search" target="_blank">Full g / h / f trace ↗</a>`;
    },
  },
  {
    id: "bridge", cam: "focus", mode: "bridge", clock: false,
    legend: () => `<div><span class="ln" style="background:#94a3b8;height:6px"></span>2024: one shuttle</div><div><span class="ln" style="background:#fde047"></span>AI: main bus bridge</div><div><span class="ln" style="background:#c4b5fd"></span>AI: split shuttle (found by search)</div>`,
    html: () => {
      const fs = finalState(), ds = fs.terminal_designs;
      const ext = fs.extras && fs.extras["0"];
      const base = ds.find((d) => d.extra == null && d.a === fs.terminals["0"][0] && d.b === fs.terminals["0"][1]);
      const best = ext ? ds.find((d) => d.extra === ext) : base;
      return `<div class="kicker violet">Decision 4 · Bus design, evaluated with A*</div><h1>Where should replacement buses run?</h1>
      <p class="lead">In 2024 one shuttle ran between the stations either side of the break, and almost everyone boarded the train at one end.</p>
      <p>The AI tries <b>${ds.length} bridge designs</b>: different end stations, plus an optional second "split" shuttle. For each one it routes every passenger with crowd-aware A* and scores the result:</p>
      <div class="formula">J = average delay (incl. queues)
  + 10 × overcrowding + 100 × unserved

2024: ${short(base.a)} ⇄ ${short(base.b)}
      J = <span class="v">${fmt(base.objective, 1)}</span>
AI:   same + split shuttle → ${ext ? short(ext) : "none"}
      J = <span class="r">${fmt(best.objective, 1)}</span>  (lower is better)</div>
      <p>${ext ? `The search adds a <b>split shuttle to ${short(ext)}</b>. Passengers heading north no longer all have to squeeze into ${short(base.a)}. Same 30 buses in total.` : "Here the 2024 design is already the best."}</p>
      <a class="deep" href="/explorer#bridge" target="_blank">All designs and scores ↗</a>`;
    },
  },
  {
    id: "ai", cam: "city", mode: "plain", clock: false,
    html: () => `<div class="kicker violet">Our AI</div><h1>Three AI techniques, one response</h1>
      <p class="lead">They run together every time a station closes, and finish in seconds:</p>
      <div class="pipeline">
        <div><span class="ico">🌧</span><div><div class="t">Storm and closures (simulation)</div><div class="s">the four real stations, timed by the flood model</div></div></div>
        <div class="arrow">↓</div>
        <div><span class="ico">⚖</span><div><div class="t">1 · Fuzzy logic</div><div class="s">priority of every station → staff, and urgency for the GA</div></div></div>
        <div class="arrow">↓</div>
        <div><span class="ico">🧭</span><div><div class="t">2 · Crowd-aware A*</div><div class="s">a route for every stranded passenger, and the score of every bus design</div></div></div>
        <div class="arrow">↓</div>
        <div><span class="ico">🧬</span><div><div class="t">3 · Genetic algorithm</div><div class="s">where the 5 relief hubs go</div></div></div>
      </div>
      <p>Same storm, same closures, same passengers, same 30 buses. <b>Only the decisions change.</b></p>
      <button class="cta" onclick="go(ch + 1)">Rerun 16 April 2024 with our AI ▶</button>`,
  },
  {
    id: "rerun", cam: "focus", mode: "sim", policy: "ai", hud: true, play: [9.0, 21.5], legend: () => legendCrowd + legendRelief("ai"),
    html: () => `<div class="kicker violet">Act 3 · 16 April 2024, with our AI</div><h1>The same day, handled differently</h1>
      <p class="lead">The same four stations close at the same times. Now:</p>
      <ul><li><span style="color:#c4b5fd">●</span> <b>Relief hubs</b> placed by the GA</li>
      <li><span style="color:#fde047">●</span> A <b>bus bridge</b> plus a <span style="color:#c4b5fd">split shuttle</span>, the design that scored best under A*</li>
      <li>Passengers routed by <b>crowd-aware A*</b>, spread across stations</li>
      <li>Staff sent by <b>fuzzy priority</b></li></ul>
      <p>Watch ${short(SIM.summary.baseline.worst_station)} again in the evening peak, and the counters.</p>`,
  },
  {
    id: "split", cam: "split", mode: "sim", split: true, hud: true, play: [14.0, 21.5], legend: () => legendCrowd,
    html: () => `<div class="kicker">Act 4 · Side by side</div><h1>2024-style vs our AI</h1>
      <p class="lead"><b style="color:#fca5a5">Left</b>: the 2024-style response. <b style="color:#c4b5fd">Right</b>: our AI. Same storm, same moment.</p>
      <p>Compare the height of the columns at the busiest stations, and the counters at the top of each map.</p>`,
  },
  {
    id: "difference", cam: "focus", mode: "sim", policy: "ai", center: true, freeze: () => PEAK, clock: false,
    html: () => {
      const a = SIM.summary.ai, b = SIM.summary.baseline;
      const row = (label, x, y, unit = "", lowerBetter = true, d = 0) => {
        const good = lowerBetter ? y < x : y > x;
        // for values that are already percentages, show the change in points, not a relative %
        const chg = unit === "%" ? `${y - x > 0 ? "+" : ""}${fmt(y - x)} pts` : `${pct(y, x) > 0 ? "+" : ""}${pct(y, x)}%`;
        return `<div class="vs"><div class="l">${fmt(x, d)}${unit}</div><div class="m">${label} <span class="delta ${good ? "" : "bad"}">${chg}</span></div><div class="r">${fmt(y, d)}${unit}</div></div>`;
      };
      const R = (m, sc) => cmpRow(m, sc);
      const multi = (sc) => {
        const rows = [["gave_up", "people gave up on the metro", 0, ""], ["waiting_person_hours", "hours spent queuing", 0, ""],
          ["worst_station_waiting", "peak queue at the worst station", 0, ""], ["avg_extra_min", "average extra trip time", 1, " min"],
          ["covered_pct", "reach help within 10 min", 0, "%"], ["unserved_pct", "unserved trips", 1, "%"], ["staffed_critical_pct", "critical stations staffed", 0, "%"]];
        return rows.map(([m, label, d, u]) => {
          const r = R(m, sc);
          if (!r) return "";
          const good = r.better_if === "lower" ? r.diff_mean < -1e-9 : r.diff_mean > 1e-9, bad = r.better_if === "lower" ? r.diff_mean > 1e-9 : r.diff_mean < -1e-9;
          const chg = u === "%" ? `${r.diff_mean > 0 ? "+" : ""}${fmt(r.diff_mean, d)} pts` : r.pct_change == null ? "–" : `${r.pct_change > 0 ? "+" : ""}${fmt(r.pct_change)}%`;
          return `<tr><td>${label}</td><td class="n">${pm(r.baseline_mean, r.baseline_std, d)}${u}</td><td class="n"><b>${pm(r.ai_mean, r.ai_std, d)}${u}</b></td><td class="n"><span class="delta ${good ? "" : bad ? "bad" : ""}">${chg}</span></td><td class="n">${r.ai_better_seeds}/${r.n}</td></tr>`;
        }).join("");
      };
      const table = (sc, title) => (R("gave_up", sc) ? `<div class="box"><b>${title}</b> · mean ± std over ${R("gave_up", sc).n} runs (seeds 0–${R("gave_up", sc).n - 1})
        <table class="rt"><tr><th></th><th class="n">2024-style</th><th class="n">Our AI</th><th class="n">change</th><th class="n">AI better</th></tr>${multi(sc)}</table></div>` : "");
      const ex = EXT ? `<p><b>Stress test: extreme storm</b> (10 stations closed). People who gave up: ${fmt(EXT.baseline.gave_up)} → <b>${fmt(EXT.ai.gave_up)}</b>. Peak crowding: ${fmt(EXT.baseline.peak_ratio, 1)}× → <b>${fmt(EXT.ai.peak_ratio, 1)}×</b>. Unserved trips rise slightly (${fmt(EXT.baseline.unserved_pct, 1)}% → ${fmt(EXT.ai.unserved_pct, 1)}%): an honest trade-off.</p>` : "";
      const chart = Charts.line({ x: SIM.hours, series: [{ y: SIM.steps.baseline.map((s) => s.m.waiting), color: "#f87171", label: "2024-style", width: 2.2 }, { y: SIM.steps.ai.map((s) => s.m.waiting), color: "#a78bfa", label: "Our AI", width: 2.6 }], xFmt: hhmm, yMin: 0, h: 170, w: 680 });
      if (RES && RES.available) {
        return `<div class="kicker">The difference</div><h1>Same storm. Better decisions.</h1>
        ${table("april_2024_replay", "16 April 2024 replay")}
        <div class="box"><b>People waiting on platforms through the day</b> <span class="hint">(this run, seed ${SIM.seed})</span>${chart}</div>
        ${table("extreme_storm", "Stress test: extreme storm")}
        <p class="hint">"AI better" = runs where the AI beat the 2024-style response on that metric. The AI is not better everywhere: see the red changes. Modelled on real RTA data. Full tables in results/.</p>`;
      }
      return `<div class="kicker">The difference</div><h1>Same storm. Better decisions.</h1>
      <div class="vs" style="margin-bottom:4px"><div class="l" style="color:#fca5a5">2024-style</div><div class="m"></div><div class="r">Our AI</div></div>
      ${row("people gave up on the metro", b.gave_up, a.gave_up)}
      ${row("hours spent queuing", b.waiting_person_hours, a.waiting_person_hours)}
      ${row(`peak queue at ${short(b.worst_station)}`, b.worst_station_waiting, SIM.steps.ai.reduce((m, s) => Math.max(m, s.queue[IDX[b.worst_station]]), 0))}
      ${row("average extra trip time", b.avg_extra_min, a.avg_extra_min, " min", true, 1)}
      ${row("reach help within 10 min", b.covered_pct, a.covered_pct, "%", false)}
      <div class="box" style="margin-top:10px"><b>People waiting on platforms, through the day</b>${chart}</div>
      ${ex}
      <p class="hint">Single run (seed ${SIM.seed}): run scripts/run_all.py for the 30-run statistics.</p>`;
    },
  },
  {
    id: "end", cam: "city", mode: "plain", clock: false,
    html: () => `<div class="kicker">Thank you</div><h1>Dubai Metro Flood Response AI</h1>
      <p class="lead">Three AI techniques: <b>fuzzy logic</b> decides who needs help first, a <b>genetic algorithm</b> decides where help goes, and <b>A* search</b> decides how every stranded passenger gets home and which bus design works best.</p>
      <p>Built on real RTA open data: 53 stations, 85 km of track, 8 years of ridership and 2,682 bus stops. Every technique is written from scratch and covered by 43 unit tests, and every result is reproducible from a seed.</p>
      <a class="deep" href="/explorer" target="_blank">Open the algorithm explorer ↗</a>
      <p class="hint" style="margin-top:14px">CSCI218 Foundations of AI · UOWD. Simulated scenario on real RTA open data.</p>`,
  },
];

/* ================================================================ chapter engine */
function go(i) {
  i = Math.max(0, Math.min(CHAPTERS.length - 1, i));
  ch = i;
  const c = CHAPTERS[i];
  document.querySelectorAll("#dots button").forEach((b, k) => { b.classList.toggle("on", k === i); });
  $("prev").disabled = i === 0;
  $("next").textContent = i === CHAPTERS.length - 1 ? "Start over ↺" : "Next →";
  document.body.classList.toggle("split", !!c.split);
  document.body.classList.toggle("wide-card", !!c.wide);
  document.body.classList.toggle("center", !!c.center);
  $("paneB").classList.toggle("hidden", !c.split);
  views[0].policy = c.split ? "baseline" : c.policy || "baseline";
  views[1].policy = "ai";
  views.forEach((v) => (v.mode = c.mode));
  $("tagA").textContent = "2024-style response"; $("tagA").className = "ptag base";
  $("tagB").textContent = "Our AI"; $("tagB").className = "ptag ai";
  setTimeout(() => views.forEach((v) => v.map.resize()), 20);
  const cam = CAM[c.cam || "city"];
  // time
  const clockOn = c.clock !== false && (c.play || c.freeze);
  $("clockWrap").classList.toggle("off", !clockOn);
  if (c.play) { stepF = stepOf(c.play[0]); playTo = stepOf(c.play[1]); playing = true; }
  else if (c.freeze) { playing = false; stepF = c.freeze(); playTo = null; }
  else { playing = false; stepF = PEAK; }
  setStep(Math.floor(stepF));
  $("play").textContent = playing ? "❚❚" : "▶";
  animStart = performance.now();
  document.body.classList.toggle("show-explorer", ["fuzzy", "hubs", "astar", "bridge", "end"].includes(c.id));
  // card + hud + legend
  const card = $("card");
  card.classList.add("fade");
  setTimeout(() => {
    $("cardInner").innerHTML = c.html(); $("cardInner").scrollTop = 0; card.classList.remove("fade"); renderCardLive();
    // frame the map in the space NOT covered by the panel, so stations never sit behind it
    // set the padding on both maps first: a camera-sync event must never interrupt a flight before it applies
    const padding = camPadding(c);
    views.forEach((v) => v.map.setPadding(padding));
    if (c.split) views[1].map.jumpTo(cam);
    views[0].map.flyTo({ ...cam, duration: i === 0 ? 0 : 2200, essential: true });
  }, 180);
  $("legend").innerHTML = c.legend ? c.legend() : "";
  $("hudA").classList.toggle("on", !!c.hud);
  $("hudB").classList.toggle("on", !!c.hud && !!c.split);
  try { history.replaceState(null, "", "#" + c.id); } catch (e) { /* ignore */ }
}
window.go = go;

/** Map padding that keeps the area under the narrative panel (and the HUD) out of the framed view.
 *  A tall panel pushes the view right; a short panel (split view) pushes it down. */
function camPadding(c) {
  const none = { left: 0, right: 0, top: 0, bottom: 0 };
  if (c.center || window.innerWidth < 900) return none;
  const r = $("cardInner").getBoundingClientRect();
  const paneW = $("paneA").getBoundingClientRect().width, H = window.innerHeight;
  const hudW = c.hud && !c.split ? 250 : 0;
  if (r.height < H * 0.4 || r.right > paneW * 0.6) return { left: 0, right: 0, top: Math.round(r.bottom + 10), bottom: 90 };
  return { left: Math.round(r.right + 20), right: hudW, top: 10, bottom: 90 };
}
window.addEventListener("resize", () => { if (SIM) views.forEach((v) => v.map.setPadding(camPadding(CHAPTERS[ch]))); });

function setStep(s) {
  step = Math.max(0, Math.min(SIM.hours.length - 1, s));
  $("scrub").value = step;
  $("clock").textContent = hhmm(SIM.hours[step]);
  const c = CHAPTERS[ch];
  if (c.hud) { hud($("hudA"), views[0].policy); if (c.split) hud($("hudB"), "ai"); }
}

function renderCardLive() {
  const c = CHAPTERS[ch];
  if (c.id === "hubs") {
    const g = finalState().ga, k = Math.min(GA_GEN, g.curve_best.length - 1);
    const el = $("gaGen"), f = $("gaFit"), chart = $("gaChart");
    if (!el) return;
    el.textContent = `Generation ${k}`;
    f.textContent = fmt(g.curve_best[k], 3);
    chart.innerHTML = Charts.line({ x: g.curve_best.map((_, j) => j), series: [{ y: g.curve_best.map((v, j) => (j <= k ? v : null)), color: "#a78bfa", label: "best", width: 2.4 }, { y: g.curve_mean.map((v, j) => (j <= k ? v : null)), color: "#a78bfa77", label: "mean" }],
      hlines: [{ y: g.greedy, color: "#f59e0b", label: "greedy" }, { y: g.random, color: "#64748b", label: "random" }], h: 120, w: 380, xFmt: (v) => v.toFixed(0), yMin: Math.min(g.random, ...g.curve_mean) });
  }
}

/* ================================================================ rain */
function drawRain(v, dt, on) {
  const c = v.canvas, ctx = v.ctx;
  if (c.width !== c.clientWidth) c.width = c.clientWidth;
  if (c.height !== c.clientHeight) c.height = c.clientHeight;
  ctx.clearRect(0, 0, c.width, c.height);
  if (!on) return;
  const target = Math.min(420, Math.round(SIM.storm_track[step][2] * 8));
  while (v.drops.length < target) v.drops.push({ x: Math.random() * c.width, y: Math.random() * c.height, s: 9 + Math.random() * 8, l: 7 + Math.random() * 11 });
  v.drops.length = target;
  ctx.strokeStyle = "rgba(190,215,255,.28)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (const d of v.drops) {
    d.y += d.s * dt * 0.06; d.x -= d.s * dt * 0.012;
    if (d.y > c.height) { d.y = -d.l; d.x = Math.random() * c.width * 1.1; }
    ctx.moveTo(d.x, d.y); ctx.lineTo(d.x - d.l * 0.2, d.y + d.l);
  }
  ctx.stroke();
}

/* ================================================================ loop */
const MODES = { cover: () => tracks(), sim: simLayers, fuzzy: fuzzyLayers, ga: gaLayers, search: searchLayers, bridge: bridgeLayers, plain: plainLayers };
let last = performance.now(), lastDraw = 0, lastCard = 0;
function frame(now) {
  const dt = Math.min(64, now - last); last = now;
  if (SIM) {
    const c = CHAPTERS[ch];
    if (playing && playTo != null) {
      stepF += (dt / 1000) * 3.2;
      if (stepF >= playTo) { stepF = playTo; playing = false; $("play").textContent = "▶"; }
      if (Math.floor(stepF) !== step) setStep(Math.floor(stepF));
    }
    if (now - lastDraw > 50) { // ~20 fps for layers is plenty and keeps it smooth
      lastDraw = now;
      for (const v of views) {
        if (v === views[1] && !c.split) continue;
        v.overlay.setProps({ layers: MODES[v.mode](v, now) });
      }
    }
    if (c.anim && now - lastCard > 120) { lastCard = now; renderCardLive(); }
    const rainOn = c.mode === "sim" && SIM.storm_track[step][2] > 0;
    drawRain(views[0], dt, rainOn);
    if (c.split) drawRain(views[1], dt, rainOn);
  }
  requestAnimationFrame(frame);
}

/* ================================================================ controls */
$("next").addEventListener("click", () => go(ch === CHAPTERS.length - 1 ? 0 : ch + 1));
$("prev").addEventListener("click", () => go(ch - 1));
$("play").addEventListener("click", () => {
  const c = CHAPTERS[ch];
  if (!playing && c.play && step >= stepOf(c.play[1])) stepF = stepOf(c.play[0]);
  playTo = c.play ? stepOf(c.play[1]) : SIM.hours.length - 1;
  playing = !playing;
  $("play").textContent = playing ? "❚❚" : "▶";
});
$("scrub").addEventListener("input", () => { playing = false; $("play").textContent = "▶"; stepF = +$("scrub").value; setStep(stepF); });
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "ArrowRight" || e.key === "PageDown") go(ch + 1);
  if (e.key === "ArrowLeft" || e.key === "PageUp") go(ch - 1);
  if (e.key === " ") { e.preventDefault(); $("play").click(); }
  if (e.key === "r" || e.key === "R") { animStart = performance.now(); const c = CHAPTERS[ch]; if (c.play) { stepF = stepOf(c.play[0]); playTo = stepOf(c.play[1]); playing = true; } }
});

async function init() {
  views.push(makeView("mapA", "rainA"), makeView("mapB", "rainB"));
  syncCams();
  $("dots").innerHTML = CHAPTERS.map((c, i) => `<button title="${c.id}" aria-label="Chapter ${i + 1}"></button>`).join("");
  document.querySelectorAll("#dots button").forEach((b, i) => b.addEventListener("click", () => go(i)));
  NET = await (await fetch("/api/network")).json();
  NET.stations.forEach((s, i) => (IDX[s.name] = i));
  SIM = await (await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: "april_2024_replay", seed: 42 }) })).json();
  $("scrub").max = SIM.hours.length - 1;
  PEAK = stepOf(SIM.summary.baseline.peak_waiting_time);
  MAXPEOPLE = Math.max(...["baseline", "ai"].flatMap((p) => SIM.steps[p].map((s) => Math.max(...s.load.map((l, i) => l + s.queue[i])))));
  const bb = IDX[SIM.summary.baseline.worst_station], st = stateAt(PEAK), sb = SIM.steps.baseline[PEAK];
  const [fz, sr] = await Promise.all([
    fetch(`/api/fuzzy?load=${sb.ratio[bb]}&flood=${SIM.water[PEAK][bb] / NET.threshold_mm}&hub=${NET.stations[bb].interchange ? 1 : 0}&dist=${st && st.dist ? st.dist[bb] : 10}`).then((r) => r.json()),
    SIM.search ? fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ origin: SIM.search.origin, dest: SIM.search.dest, closed: SIM.closed_final }) }).then((r) => r.json()) : null,
  ]);
  FUZ = fz; SEARCH = sr;
  try { RES = await (await fetch("/api/results")).json(); } catch (e) { RES = null; }
  fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: "extreme_storm", seed: 42 }) })
    .then((r) => r.json()).then((x) => { EXT = x.summary; if (CHAPTERS[ch].id === "difference") go(ch); }).catch(() => {});
  $("loading").classList.add("done");
  const start = CHAPTERS.findIndex((c) => "#" + c.id === location.hash);
  requestAnimationFrame(frame);
  go(start >= 0 ? start : 0);
  views[0].map.once("idle", () => { if (ch === 0) views[0].map.flyTo({ ...CAM.city, pitch: 30, duration: 6000, essential: true }); });
}
init();
