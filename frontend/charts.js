/* Tiny SVG chart helpers: line charts and horizontal bar charts, returned as SVG strings. */
const Charts = (() => {
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const nice = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toFixed(2));

  function line(o) {
    const W = o.w || 520, H = o.h || 200, m = { l: 40, r: 12, t: 12, b: 26, ...(o.margin || {}) };
    const xs = o.x;
    const all = o.series.flatMap((s) => s.y.filter((v) => v != null && Number.isFinite(v)));
    (o.hlines || []).forEach((h) => all.push(h.y));
    let yMin = o.yMin ?? Math.min(...all), yMax = o.yMax ?? Math.max(...all);
    if (yMax - yMin < 1e-9) { yMax += 1; yMin -= o.yMin != null ? 0 : 1; }
    const xMin = xs[0], xMax = xs[xs.length - 1];
    const X = (v) => m.l + ((v - xMin) / (xMax - xMin || 1)) * (W - m.l - m.r);
    const Y = (v) => H - m.b - ((v - yMin) / (yMax - yMin)) * (H - m.t - m.b);
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px">`;
    for (let i = 0; i <= 4; i++) {
      const v = yMin + ((yMax - yMin) * i) / 4, y = Y(v);
      s += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}"/><text x="${m.l - 6}" y="${y + 3.5}" text-anchor="end">${esc((o.yFmt || nice)(v))}</text>`;
    }
    const ticks = o.xTicks || 6;
    for (let i = 0; i <= ticks; i++) {
      const v = xMin + ((xMax - xMin) * i) / ticks;
      s += `<text x="${X(v)}" y="${H - 8}" text-anchor="middle">${esc((o.xFmt || nice)(v))}</text>`;
    }
    s += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>`;
    for (const h of o.hlines || []) {
      s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(h.y)}" y2="${Y(h.y)}" stroke="${h.color}" stroke-dasharray="5 4" stroke-width="1.3"/>`;
      if (h.label) s += `<text x="${W - m.r - 4}" y="${Y(h.y) - 4}" text-anchor="end" style="fill:${h.color}">${esc(h.label)}</text>`;
    }
    for (const sr of o.series) {
      const pts = sr.y.map((v, i) => (v == null || !Number.isFinite(v) ? null : `${X(xs[i]).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean);
      if (!pts.length) continue;
      if (sr.fill) s += `<polygon points="${X(xs[0])},${Y(yMin)} ${pts.join(" ")} ${X(xs[xs.length - 1])},${Y(yMin)}" fill="${sr.fill}" stroke="none"/>`;
      s += `<polyline points="${pts.join(" ")}" fill="none" stroke="${sr.color}" stroke-width="${sr.width || 1.8}" ${sr.dash ? `stroke-dasharray="${sr.dash}"` : ""} stroke-linejoin="round"/>`;
    }
    for (const v of o.vlines || []) {
      s += `<line x1="${X(v.x)}" x2="${X(v.x)}" y1="${m.t}" y2="${H - m.b}" stroke="${v.color}" stroke-width="${v.width || 1.5}" ${v.dash ? `stroke-dasharray="${v.dash}"` : ""}/>`;
      if (v.label) s += `<text x="${X(v.x) + 4}" y="${m.t + 10}" style="fill:${v.color}">${esc(v.label)}</text>`;
    }
    for (const p of o.points || []) s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${p.r || 4}" fill="${p.color}" stroke="#0a0d12" stroke-width="1.5"/>`;
    if (o.legend !== false) {
      let lx = m.l + 4;
      for (const sr of o.series.filter((q) => q.label)) {
        s += `<rect x="${lx}" y="${m.t - 2}" width="10" height="3" fill="${sr.color}"/><text x="${lx + 14}" y="${m.t + 2}">${esc(sr.label)}</text>`;
        lx += 22 + sr.label.length * 5.6;
      }
    }
    return s + "</svg>";
  }

  function bars(o) {
    const W = o.w || 520, rowH = o.rowH || 20, lw = o.labelW || 150;
    const H = o.items.length * rowH + 6;
    const vals = o.items.map((d) => d.value);
    const lo = Math.min(0, ...vals), hi = Math.max(o.max ?? 0, ...vals);
    const X = (v) => lw + ((v - lo) / (hi - lo || 1)) * (W - lw - 54);
    let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" style="height:${H}px">`;
    o.items.forEach((d, i) => {
      const y = 3 + i * rowH;
      const x0 = X(Math.min(0, d.value)), x1 = X(Math.max(0, d.value));
      s += `<text x="${lw - 6}" y="${y + rowH / 2 + 3.5}" text-anchor="end" ${d.bold ? 'style="fill:#e6ebf2;font-weight:600"' : ""}>${esc(d.label)}</text>`;
      s += `<rect x="${x0}" y="${y + 3}" width="${Math.max(1, x1 - x0)}" height="${rowH - 7}" rx="3" fill="${d.color || "#38bdf8"}"/>`;
      s += `<text x="${x1 + 5}" y="${y + rowH / 2 + 3.5}">${esc((o.fmt || nice)(d.value))}</text>`;
    });
    if (lo < 0) s += `<line class="axis" x1="${X(0)}" x2="${X(0)}" y1="0" y2="${H}"/>`;
    return s + "</svg>";
  }

  return { line, bars };
})();
