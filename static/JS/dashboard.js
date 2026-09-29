// ============================================================
// Defect / Inspection Dashboard — live backend-driven data layer
// Talks to the Flask API defined in app.py:
//   GET /api/defect-dashboard/types?part_number=&time_filter=
//   GET /api/chart-data?part_number=&location=&shift=&time_filter=
//   GET /api/inspection-details?status=&part_number=&location=&shift=&time_filter=
//   GET /api/trained-parts
//   GET /api/shift-stats            (today only — backend limitation)
//   GET /api/inspection/status
// ============================================================

const REFRESH_INTERVAL_MS = 5000;   // live polling cadence
const TREND_DAYS = 7;               // defects-tab trend chart window
const COLOR_PALETTE = [
  '--color-face', '--color-head', '--color-seat',
  '--color-neck', '--color-stem', '--color-other'
];
const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const SHIFT_WINDOWS = {
  'Shift A': '6:30 AM – 2:30 PM',
  'Shift B': '2:30 PM – 10:30 PM',
  'Shift C': '10:30 PM – 6:30 AM'
};

// UI -> API vocabulary for the Time Range dropdown
const TIME_RANGE_MAP = {
  'Daily': 'daily',
  'Weekly': 'weekly',
  'Monthly': 'monthly',
  '3 Months': 'monthly', // backend only understands these four buckets
  'Yearly': 'yearly'
};

let isLiveActive = true;
let pollTimer = null;
let isFetching = false;

// --- Defects tab state ---
let dataset = [];                 // [{ category, count, color }]
let trendSeries = { face: [], head: [], seat: [], other: [] };
let categoryColorMap = {};        // category label -> css var()
let previousTotals = null;        // defects-tab session-local delta badges
let lastGoodState = null;         // fallback if a fetch cycle fails

// --- Inspection tab state ---
let previousInspectionTotals = null;

// ------------------------------------------------------------
// Generic helpers
// ------------------------------------------------------------

function cssVar(name) {
  return `var(${name})`;
}

function assignColor(category) {
  if (categoryColorMap[category]) return categoryColorMap[category];
  const idx = Object.keys(categoryColorMap).length % COLOR_PALETTE.length;
  const color = cssVar(COLOR_PALETTE[idx]);
  categoryColorMap[category] = color;
  return color;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.innerText = text;
}

async function fetchJSON(url) {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (res.redirected && res.url.includes('/login')) {
    throw new Error('Session expired — please log in again.');
  }
  if (!res.ok) {
    throw new Error(`${url} responded with ${res.status}`);
  }
  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(`${url} did not return JSON (got redirected to a login/error page)`);
  }
  return res.json();
}

function getFilters() {
  const partSelect = document.getElementById('sel-part');
  const rangeSelect = document.getElementById('sel-range');
  const locationSelect = document.getElementById('sel-location');
  const shiftSelect = document.getElementById('sel-shift');

  const rawPart = partSelect ? partSelect.value : '';
  const rawRange = rangeSelect ? rangeSelect.value : 'Daily';
  const rawLocation = locationSelect ? locationSelect.value : '';
  const rawShift = shiftSelect ? shiftSelect.value : '';

  return {
    part_number: (!rawPart || rawPart === 'All Parts') ? '' : rawPart,
    location: (!rawLocation || rawLocation === 'All Plants') ? '' : rawLocation,
    shift: (!rawShift || rawShift === 'All Shifts') ? '' : rawShift,
    time_filter: TIME_RANGE_MAP[rawRange] || 'daily',
    time_label: rawRange
  };
}

// opts lets callers drop params an endpoint doesn't understand
function toQueryString(filters, opts = {}) {
  const qs = new URLSearchParams();
  if (filters.part_number) qs.set('part_number', filters.part_number);
  if (!opts.skipLocation && filters.location) qs.set('location', filters.location);
  if (!opts.skipShift && filters.shift) qs.set('shift', filters.shift);
  qs.set('time_filter', filters.time_filter);
  return qs.toString();
}

function updateScopePill(filters) {
  const pill = document.getElementById('scope-pill');
  if (!pill) return;
  const plant = filters.location || 'All Plants';
  const shift = filters.shift || 'All Shifts';
  pill.innerText = `${plant} · ${shift}`;
}

// ------------------------------------------------------------
// Populate PART NUMBER dropdown from /api/trained-parts
// ------------------------------------------------------------
async function loadPartNumbers() {
  const select = document.getElementById('sel-part');
  if (!select) return;

  try {
    const data = await fetchJSON('/api/trained-parts');
    const parts = Array.isArray(data.parts) ? data.parts : [];
    const previousValue = select.value;

    select.innerHTML = '<option>All Parts</option>';
    parts
      .slice()
      .sort((a, b) => String(a.part_number).localeCompare(String(b.part_number)))
      .forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.part_number;
        opt.textContent = p.part_number;
        select.appendChild(opt);
      });

    const stillExists = Array.from(select.options).some(o => o.value === previousValue);
    if (stillExists) select.value = previousValue;
  } catch (err) {
    console.error('Failed to load part numbers:', err);
  }
}

// PLANT LOCATION options aren't exposed by a dedicated endpoint, so they're
// harvested from whatever inspection rows we already had to fetch.
function populateLocationOptions(rows) {
  const select = document.getElementById('sel-location');
  if (!select) return;

  const previousValue = select.value;
  const locations = Array.from(new Set(rows.map(r => r.Location).filter(Boolean))).sort();

  select.innerHTML = '<option>All Plants</option>';
  locations.forEach(loc => {
    const opt = document.createElement('option');
    opt.value = loc;
    opt.textContent = loc;
    select.appendChild(opt);
  });

  const stillExists = Array.from(select.options).some(o => o.value === previousValue);
  if (stillExists) select.value = previousValue;
}

// ============================================================
// DEFECTS TAB
// ============================================================

async function fetchDefectData(filters) {
  const qs = toQueryString(filters);

  const [typesResult, totalsResult] = await Promise.allSettled([
    fetchJSON(`/api/defect-dashboard/types?${qs}`),
    fetchJSON(`/api/chart-data?${qs}`)
  ]);

  if (typesResult.status === 'rejected') throw typesResult.reason;
  const typesData = typesResult.value;
  const totals = totalsResult.status === 'fulfilled'
    ? totalsResult.value
    : { accepted: 0, rejected: 0, total: 0 };

  const rows = Array.isArray(typesData.data) ? typesData.data : [];
  const newDataset = rows
    .filter(r => r.label)
    .map(r => ({
      category: r.label,
      count: r.count,
      color: assignColor(r.label)
    }))
    .sort((a, b) => b.count - a.count);

  // Weekly rejected rows, used to build the 7-day trend curves.
  let trendRows = [];
  try {
    const trendQs = toQueryString({ ...filters, time_filter: 'weekly' });
    const detail = await fetchJSON(`/api/inspection-details?status=rejected&${trendQs}`);
    trendRows = Array.isArray(detail) ? detail : [];
  } catch (err) {
    console.warn('Trend data unavailable, keeping last known trend:', err);
  }

  return { dataset: newDataset, totals, trendRows };
}

function buildDefectTrendSeries(rows) {
  const dayKeys = [];
  const today = new Date();
  for (let i = TREND_DAYS - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    dayKeys.push(d.toISOString().slice(0, 10));
  }

  const series = {
    face: new Array(TREND_DAYS).fill(0),
    head: new Array(TREND_DAYS).fill(0),
    seat: new Array(TREND_DAYS).fill(0),
    other: new Array(TREND_DAYS).fill(0)
  };

  rows.forEach(row => {
    const ts = row['Timestamp'];
    if (!ts) return;
    const dayKey = String(ts).slice(0, 10);
    const idx = dayKeys.indexOf(dayKey);
    if (idx === -1) return;

    const type = String(row['Defect Type'] || '').toLowerCase();
    if (type.includes('face')) series.face[idx] += 1;
    else if (type.includes('head')) series.head[idx] += 1;
    else if (type.includes('seat')) series.seat[idx] += 1;
    else series.other[idx] += 1;
  });

  return series;
}

function buildSvgPath(dataPoints) {
  const width = 500;
  const height = 180;
  if (!dataPoints || dataPoints.length < 2) return '';
  const step = width / (dataPoints.length - 1);
  const maxVal = Math.max(5, ...dataPoints);

  const points = dataPoints.map((val, idx) => ({
    x: idx * step,
    y: height - (val / maxVal) * height
  }));

  return points.reduce((acc, pt, i, a) => {
    if (i === 0) return `M ${pt.x},${pt.y}`;
    const prev = a[i - 1];
    const cx1 = prev.x + step / 2;
    const cy1 = prev.y;
    const cx2 = pt.x - step / 2;
    const cy2 = pt.y;
    return `${acc} C ${cx1},${cy1} ${cx2},${cy2} ${pt.x},${pt.y}`;
  }, '');
}

function renderDefectKpis(totals) {
  const totalCount = dataset.reduce((acc, curr) => acc + curr.count, 0);
  const topDefect = dataset[0];
  const top3Total = dataset.slice(0, 3).reduce((acc, curr) => acc + curr.count, 0);
  const rejectRate = totals.total > 0 ? (totals.rejected / totals.total) * 100 : 0;

  setText('kpi-total', totalCount || 0);
  setText('kpi-cat-count', `Across ${dataset.length} categories`);

  if (topDefect) {
    setText('kpi-top-name', topDefect.category);
    setText('kpi-top-sub', `${topDefect.count} units · ${totalCount ? ((topDefect.count / totalCount) * 100).toFixed(1) : '0.0'}% of defects`);
  } else {
    setText('kpi-top-name', '—');
    setText('kpi-top-sub', 'No rejected units in range');
  }

  setText('kpi-top3-share', totalCount ? `${((top3Total / totalCount) * 100).toFixed(1)}%` : '0.0%');

  const rejectRateEl = document.querySelector('#defects-tab .kpi-row .kpi-card:nth-child(4) .kpi-num');
  if (rejectRateEl) rejectRateEl.innerText = `${rejectRate.toFixed(1)}%`;

  if (previousTotals) {
    updateDeltaBadge('#defects-tab .kpi-row .kpi-card:nth-child(1) .kpi-badge', previousTotals.rejected, totalCount, true);
    const prevRate = previousTotals.total ? (previousTotals.rejected / previousTotals.total) * 100 : 0;
    updateDeltaBadge('#defects-tab .kpi-row .kpi-card:nth-child(4) .kpi-badge', prevRate, rejectRate, true);
  }

  previousTotals = totals;
}

function updateDeltaBadge(selector, prevVal, newVal, invertColor) {
  const el = document.querySelector(selector);
  if (!el || prevVal === null || prevVal === undefined) return;
  const diff = newVal - prevVal;
  el.classList.remove('badge-danger', 'badge-success', 'badge-neutral');
  if (diff === 0) {
    el.textContent = '– 0%';
    el.classList.add('badge-neutral');
    return;
  }
  const pct = prevVal ? Math.abs((diff / prevVal) * 100).toFixed(0) : 0;
  const up = diff > 0;
  el.textContent = `${up ? '↗' : '↘'} ${pct}%`;
  const isGood = invertColor ? !up : up;
  el.classList.add(isGood ? 'badge-success' : 'badge-danger');
}

function renderBarChart() {
  const barBox = document.getElementById('defect-bar-chart');
  if (!barBox) return;
  barBox.innerHTML = '';

  if (dataset.length === 0) {
    barBox.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No rejected units in this range.</div>';
    return;
  }

  const maxCount = Math.max(...dataset.map(d => d.count));
  dataset.forEach(item => {
    const heightPct = (item.count / maxCount) * 100;
    const col = document.createElement('div');
    col.className = 'bar-col';
    col.innerHTML = `
      <div class="bar-rect" style="height:${heightPct}%; background-color:${item.color};" data-val="${item.count}"></div>
      <span class="bar-text">${item.category}</span>
    `;
    barBox.appendChild(col);
  });
}

function renderPareto() {
  const paretoBox = document.getElementById('pareto-container');
  if (!paretoBox) return;
  paretoBox.innerHTML = '';

  if (dataset.length === 0) {
    paretoBox.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No data to rank.</div>';
    return;
  }

  const totalCount = dataset.reduce((acc, curr) => acc + curr.count, 0);
  const maxCount = Math.max(...dataset.map(d => d.count));
  let accum = 0;

  dataset.forEach((item, index) => {
    accum += item.count;
    const cumPct = totalCount ? Math.round((accum / totalCount) * 100) : 0;
    const relWidth = (item.count / maxCount) * 100;

    const row = document.createElement('div');
    row.className = 'pareto-row';
    row.innerHTML = `
      <span class="pareto-idx">${String(index + 1).padStart(2, '0')}</span>
      <span class="pareto-label">${item.category}</span>
      <div class="pareto-track">
        <div class="pareto-fill" style="width:${relWidth}%; background-color:${item.color};"></div>
      </div>
      <span class="pareto-val">${item.count}</span>
      <span class="pareto-pct">${cumPct}%</span>
    `;
    paretoBox.appendChild(row);
  });
}

function renderDefectTrend() {
  const setPath = (id, d) => {
    const el = document.getElementById(id);
    if (el) el.setAttribute('d', d);
  };
  setPath('path-face', buildSvgPath(trendSeries.face));
  setPath('path-head', buildSvgPath(trendSeries.head));
  setPath('path-seat', buildSvgPath(trendSeries.seat));
  setPath('path-other', buildSvgPath(trendSeries.other));
}

async function refreshDefectsTab(filters) {
  const { dataset: newDataset, totals, trendRows } = await fetchDefectData(filters);
  dataset = newDataset;
  trendSeries = buildDefectTrendSeries(trendRows);
  lastGoodState = { dataset, trendSeries, totals };

  renderDefectKpis(totals);
  renderBarChart();
  renderPareto();
  renderDefectTrend();
}

// ============================================================
// INSPECTION TAB
// ============================================================

async function fetchInspectionDetailRows(filters) {
  const qs = toQueryString({ ...filters, time_filter: 'weekly' });

  const [acceptedRes, rejectedRes] = await Promise.allSettled([
    fetchJSON(`/api/inspection-details?status=accepted&${qs}`),
    fetchJSON(`/api/inspection-details?status=rejected&${qs}`)
  ]);

  const accepted = acceptedRes.status === 'fulfilled' && Array.isArray(acceptedRes.value) ? acceptedRes.value : [];
  const rejected = rejectedRes.status === 'fulfilled' && Array.isArray(rejectedRes.value) ? rejectedRes.value : [];
  return { accepted, rejected };
}

function renderInspectionKpis(totals) {
  const total = totals.total || 0;
  const accepted = totals.accepted || 0;
  const rejected = totals.rejected || 0;
  const passRate = total > 0 ? (accepted / total) * 100 : 0;

  setText('insp-kpi-total', total);
  setText('insp-kpi-accepted', accepted);
  setText('insp-kpi-rejected', rejected);
  setText('insp-kpi-pass', `${passRate.toFixed(1)}%`);
  setText('insp-kpi-accepted-sub', `${total ? ((accepted / total) * 100).toFixed(1) : '0.0'}% of total inspected`);
  setText('insp-kpi-rejected-sub', `${total ? ((rejected / total) * 100).toFixed(1) : '0.0'}% of total inspected`);
  setText('insp-kpi-pass-sub', `Target 95.0% · gap ${(95 - passRate).toFixed(1)} pts`);

  if (previousInspectionTotals) {
    updateDeltaBadge('#insp-kpi-total-badge', previousInspectionTotals.total, total, false);
    updateDeltaBadge('#insp-kpi-accepted-badge', previousInspectionTotals.accepted, accepted, false);
    updateDeltaBadge('#insp-kpi-rejected-badge', previousInspectionTotals.rejected, rejected, true);
    const prevRate = previousInspectionTotals.total ? (previousInspectionTotals.accepted / previousInspectionTotals.total) * 100 : 0;
    updateDeltaBadge('#insp-kpi-pass-badge', prevRate, passRate, false);
  }

  previousInspectionTotals = totals;
}

function renderGauge(totals) {
  const fillPath = document.getElementById('gauge-fill');
  const needle = document.getElementById('gauge-needle');
  if (!fillPath || !needle) return;

  const total = totals.total || 0;
  const rate = total > 0 ? (totals.accepted / total) * 100 : 0;
  const clamped = Math.min(100, Math.max(0, rate));

  setText('gauge-value', `${rate.toFixed(1)}%`);
  setText('gauge-accepted', totals.accepted || 0);
  setText('gauge-rejected', totals.rejected || 0);

  const target = 95;
  const gap = rate - target;
  const gapEl = document.getElementById('gauge-gap');
  if (gapEl) {
    gapEl.innerText = `${gap >= 0 ? '+' : '−'}${Math.abs(gap).toFixed(1)} pts`;
    gapEl.style.color = gap >= 0 ? 'var(--color-stem)' : 'var(--color-face)';
  }

  // Semicircle arc: center (120,120), radius 100, sweeps from 180° (0%) to 0° (100%)
  const cx = 120, cy = 120, r = 100, needleLen = 78;
  const angleDeg = 180 - (clamped / 100) * 180;
  const rad = (angleDeg * Math.PI) / 180;
  const endX = cx + r * Math.cos(rad);
  const endY = cy - r * Math.sin(rad);

  fillPath.setAttribute('d', `M 20 120 A 100 100 0 0 1 ${endX.toFixed(2)},${endY.toFixed(2)}`);
  fillPath.setAttribute('stroke', rate >= 95 ? 'var(--color-stem)' : rate >= 90 ? 'var(--color-neck)' : 'var(--color-face)');

  const nx = cx + needleLen * Math.cos(rad);
  const ny = cy - needleLen * Math.sin(rad);
  needle.setAttribute('x2', nx.toFixed(2));
  needle.setAttribute('y2', ny.toFixed(2));
}

function aggregateByWeekday(rows) {
  const buckets = new Array(7).fill(0); // 0=Mon .. 6=Sun
  rows.forEach(r => {
    const ts = r['Timestamp'];
    if (!ts) return;
    const d = new Date(String(ts).replace(' ', 'T'));
    if (isNaN(d.getTime())) return;
    const day = (d.getDay() + 6) % 7; // convert JS 0=Sun..6=Sat -> 0=Mon..6=Sun
    buckets[day] += 1;
  });
  return buckets;
}

function buildAreaSeries(values, sharedMax) {
  const width = 500;
  const baseline = 200;
  const maxVal = sharedMax;
  const step = width / (values.length - 1);
  const points = values.map((v, i) => ({ x: i * step, y: baseline - (v / maxVal) * baseline }));

  const line = points.reduce((acc, pt, i, a) => {
    if (i === 0) return `M ${pt.x},${pt.y}`;
    const prev = a[i - 1];
    const cx1 = prev.x + step / 2, cy1 = prev.y, cx2 = pt.x - step / 2, cy2 = pt.y;
    return `${acc} C ${cx1},${cy1} ${cx2},${cy2} ${pt.x},${pt.y}`;
  }, '');

  const fill = `${line} L ${points[points.length - 1].x},${baseline} L ${points[0].x},${baseline} Z`;
  return { line, fill };
}

function renderInspectionTrend(acceptedRows, rejectedRows) {
  const acceptedByDay = aggregateByWeekday(acceptedRows);
  const rejectedByDay = aggregateByWeekday(rejectedRows);

  // Both lines must share ONE max so their heights are comparable — if each
  // line is scaled to its own max independently, whichever series has the
  // smaller raw counts (often "accepted" on a bad week, or vice versa) gets
  // visually flattened even though the underlying data is updating fine.
  const sharedMax = Math.max(5, ...acceptedByDay, ...rejectedByDay);

  const accSeries = buildAreaSeries(acceptedByDay, sharedMax);
  const rejSeries = buildAreaSeries(rejectedByDay, sharedMax);

  const setPath = (id, d) => {
    const el = document.getElementById(id);
    if (el) el.setAttribute('d', d);
  };
  setPath('area-accepted-line', accSeries.line);
  setPath('area-accepted-fill', accSeries.fill);
  setPath('area-rejected-line', rejSeries.line);
  setPath('area-rejected-fill', rejSeries.fill);

  const labelsEl = document.getElementById('area-chart-labels');
  if (labelsEl) labelsEl.innerHTML = WEEKDAY_LABELS.map(d => `<span>${d}</span>`).join('');
}

function renderTopReasons(rejectedRows) {
  const listEl = document.getElementById('reason-list');
  if (!listEl) return;

  const counts = {};
  rejectedRows.forEach(r => {
    const type = (r['Defect Type'] || 'Unspecified').toString().trim() || 'Unspecified';
    counts[type] = (counts[type] || 0) + 1;
  });

  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6);
  listEl.innerHTML = '';

  if (entries.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No rejected units this week.</div>';
    return;
  }

  const maxVal = entries[0][1];
  entries.forEach(([label, count]) => {
    const row = document.createElement('div');
    row.className = 'reason-row';
    row.innerHTML = `
      <span class="reason-label">${label}</span>
      <div class="reason-track"><div class="reason-fill" style="width:${(count / maxVal) * 100}%;"></div></div>
      <span class="reason-val">${count}</span>
    `;
    listEl.appendChild(row);
  });
}

function renderVolumeByPlant(acceptedRows, rejectedRows) {
  const chartEl = document.getElementById('plant-bar-chart');
  if (!chartEl) return;

  const totals = {};
  const bump = (loc, key) => {
    const k = loc || 'Unknown';
    totals[k] = totals[k] || { inspected: 0, rejected: 0 };
    totals[k].inspected += 1;
    if (key === 'rejected') totals[k].rejected += 1;
  };
  acceptedRows.forEach(r => bump(r.Location, 'accepted'));
  rejectedRows.forEach(r => bump(r.Location, 'rejected'));

  const entries = Object.entries(totals).sort((a, b) => b[1].inspected - a[1].inspected).slice(0, 8);
  chartEl.innerHTML = '';

  if (entries.length === 0) {
    chartEl.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No data this week.</div>';
    return;
  }

  const maxVal = Math.max(...entries.map(([, v]) => v.inspected));
  entries.forEach(([loc, v]) => {
    const inspectedPct = (v.inspected / maxVal) * 100;
    const rejectedPct = (v.rejected / maxVal) * 100;
    const col = document.createElement('div');
    col.className = 'bar-col grouped-bar-col';
    col.innerHTML = `
      <div class="grouped-bars">
        <div class="bar-rect" style="height:${inspectedPct}%; background-color:var(--color-head);" data-val="${v.inspected}"></div>
        <div class="bar-rect bar-rect-narrow" style="height:${rejectedPct}%; background-color:var(--color-face);" data-val="${v.rejected}"></div>
      </div>
      <span class="bar-text" style="transform:none; margin-top:6px;">${loc}</span>
    `;
    chartEl.appendChild(col);
  });
}

async function renderShiftSummary() {
  const body = document.getElementById('shift-table-body');
  if (!body) return;

  try {
    const data = await fetchJSON('/api/shift-stats');
    const rows = Array.isArray(data.data) ? data.data : [];
    body.innerHTML = '';

    if (rows.length === 0) {
      body.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted); padding:12px 0;">No shift data for today.</td></tr>';
      return;
    }

    rows.forEach(r => {
      const inspected = (r.accepted || 0) + (r.rejected || 0);
      const passRate = inspected > 0 ? (r.accepted / inspected) * 100 : 0;
      const badgeClass = passRate >= 95 ? 'badge-success' : passRate >= 90 ? 'badge-neutral' : 'badge-danger';

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${r.shift}</td>
        <td>${SHIFT_WINDOWS[r.shift] || '—'}</td>
        <td>${inspected}</td>
        <td style="color:var(--color-face);">${r.rejected || 0}</td>
        <td><span class="kpi-badge ${badgeClass}">${passRate.toFixed(1)}% pass</span></td>
      `;
      body.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load shift summary:', err);
    body.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted); padding:12px 0;">Shift data unavailable.</td></tr>';
  }
}

async function refreshInspectionTab(filters) {
  try {
    const totals = await fetchJSON(`/api/chart-data?${toQueryString(filters)}`);
    renderInspectionKpis(totals);
    renderGauge(totals);
  } catch (err) {
    console.error('Inspection KPI fetch failed:', err);
  }

  try {
    const { accepted, rejected } = await fetchInspectionDetailRows(filters);
    populateLocationOptions([...accepted, ...rejected]);
    renderInspectionTrend(accepted, rejected);
    renderTopReasons(rejected);
    renderVolumeByPlant(accepted, rejected);
  } catch (err) {
    console.error('Inspection detail rows fetch failed:', err);
  }

  await renderShiftSummary();
}

async function renderStatusPill(filters) {
  const pill = document.getElementById('clock-pill');
  if (!pill) return;

  let statusLabel = 'Rejected units only';
  try {
    const status = await fetchJSON('/api/inspection/status');
    if (status.running) {
      statusLabel = status.paused ? 'Inspection paused' : 'Inspection running';
    }
  } catch (err) {
    // Non-fatal — keep default label if status endpoint isn't reachable.
  }

  const partLabel = filters.part_number || 'All parts';
  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  pill.innerText = `${statusLabel} · ${partLabel} · ${filters.time_label} · updated ${timeStr} IST`;
}

// ============================================================
// Orchestration
// ============================================================

async function refreshDashboard() {
  if (isFetching) return; // avoid overlapping requests if a cycle runs long
  isFetching = true;

  const filters = getFilters();
  updateScopePill(filters);

  try {
    await refreshDefectsTab(filters);
  } catch (err) {
    console.error('Defects tab refresh failed:', err);
    if (lastGoodState) {
      dataset = lastGoodState.dataset;
      trendSeries = lastGoodState.trendSeries;
      renderDefectKpis(lastGoodState.totals);
      renderBarChart();
      renderPareto();
      renderDefectTrend();
    }
  }

  try {
    await refreshInspectionTab(filters);
  } catch (err) {
    console.error('Inspection tab refresh failed:', err);
  }

  await renderStatusPill(filters);
  isFetching = false;
}

// Kept as `renderAll` so the "Apply filters" button (onclick="renderAll()")
// and window.onload keep working unchanged.
function renderAll() {
  refreshDashboard();
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (isLiveActive) refreshDashboard();
  }, REFRESH_INTERVAL_MS);
}

function toggleLiveMode() {
  isLiveActive = !isLiveActive;
  const btn = document.getElementById('live-btn');
  const text = document.getElementById('live-status-text');
  if (btn) btn.style.opacity = isLiveActive ? '1' : '0.4';
  if (text) text.innerText = isLiveActive ? 'LIVE' : 'PAUSED';
  if (isLiveActive) refreshDashboard(); // catch up immediately on resume
}

function switchView(tab) {
  document.getElementById('btn-tab-defects').classList.toggle('active', tab === 'defects');
  document.getElementById('btn-tab-inspection').classList.toggle('active', tab === 'inspection');
  document.getElementById('defects-tab').classList.toggle('active', tab === 'defects');
  document.getElementById('inspection-tab').classList.toggle('active', tab === 'inspection');
  document.getElementById('page-title').innerText = tab === 'defects' ? 'Defect Dashboard' : 'Valve Inspection Dashboard';
}

function applyTheme(theme) {
  document.body.setAttribute('data-theme', theme);
}

window.onload = async function () {
  await loadPartNumbers();
  await refreshDashboard();
  startPolling();
};