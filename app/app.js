"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  manifest: null,
  event: null,       // loaded aggregated dataset for the selected slug
  slug: null,        // currently selected event slug
  needed: new Set(), // bingo numbers (0..99) still required
};

// ---------------------------------------------------------------------------
// Persistence (localStorage) — remembers your card + setup between visits.
//
// Position Bingo is about the number, not the event: a "01" counts wherever you
// got it. So the card (and your pace/date setup, which reflect *you*) are stored
// ONCE and shared across all events — switching events keeps your numbers.
// ---------------------------------------------------------------------------
const STORAGE_KEY = "pbp:card";       // single global key
const LEGACY_PREFIX = "pbp:v1:";       // old per-event keys, migrated on first load

function saveState() {
  const payload = {
    needed: Array.from(state.needed).sort((a, b) => a - b),
    date: document.getElementById("target-date").value,
    useSeason: document.getElementById("use-season").checked,
    useWeather: document.getElementById("use-weather").checked,
    paceMin: document.getElementById("pace-min").value,
    paceMax: document.getElementById("pace-max").value,
    savedAt: Date.now(),
  };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    markSaved(payload.savedAt);
  } catch (e) {
    // localStorage can be unavailable (private mode / disabled). Fail quietly.
  }
}

function loadSaved() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
    return migrateLegacy();   // first run after upgrade: adopt old per-event card
  } catch (e) {
    return null;
  }
}

// One-time migration: if there's no global card yet but an old per-event card
// exists, adopt the one with the most numbers (likely the card they were using),
// save it globally, and clean up the legacy keys.
function migrateLegacy() {
  try {
    let best = null;
    const stale = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(LEGACY_PREFIX)) {
        stale.push(key);
        const data = JSON.parse(localStorage.getItem(key));
        const n = Array.isArray(data.needed) ? data.needed.length : 0;
        if (!best || n > best.n) best = { data, n };
      }
    }
    if (best) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(best.data));
      stale.forEach((k) => localStorage.removeItem(k));
      return best.data;
    }
  } catch (e) { /* ignore */ }
  return null;
}

function clearSaved() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (e) { /* ignore */ }
}

// Apply a saved payload to the UI/state. Grid + date inputs must already exist.
function applySaved(payload) {
  if (!payload) return;
  if (Array.isArray(payload.needed)) {
    setNeeded(new Set(payload.needed));
  }
  if (typeof payload.date === "string" && payload.date) {
    document.getElementById("target-date").value = payload.date;
  }
  if (typeof payload.useSeason === "boolean") {
    document.getElementById("use-season").checked = payload.useSeason;
  }
  if (typeof payload.useWeather === "boolean") {
    document.getElementById("use-weather").checked = payload.useWeather;
  }
  if (typeof payload.paceMin === "string") {
    document.getElementById("pace-min").value = payload.paceMin;
  }
  if (typeof payload.paceMax === "string") {
    document.getElementById("pace-max").value = payload.paceMax;
  }
  updateSeasonMeta();
  markSaved(payload.savedAt);
}

function markSaved(ts) {
  const el = document.getElementById("save-status");
  if (!el) return;
  if (!ts) { el.textContent = ""; return; }
  const when = new Date(ts).toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  el.textContent = `Saved automatically \u00b7 ${when}`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const pad2 = (n) => String(n).padStart(2, "0");

function fmtTime(seconds) {
  if (seconds == null || isNaN(seconds)) return "\u2014";
  seconds = Math.round(seconds);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${pad2(m)}:${pad2(s)}`;
  return `${m}:${pad2(s)}`;
}

// Parse "mm:ss" or "h:mm:ss" (or bare minutes) to seconds; null if blank/bad.
function parseTime(txt) {
  if (!txt) return null;
  txt = txt.trim();
  if (!txt) return null;
  const parts = txt.split(":").map((p) => p.trim());
  if (parts.some((p) => p === "" || isNaN(Number(p)))) return null;
  const nums = parts.map(Number);
  if (nums.length === 1) return nums[0] * 60;          // bare minutes
  if (nums.length === 2) return nums[0] * 60 + nums[1]; // mm:ss
  if (nums.length === 3) return nums[0] * 3600 + nums[1] * 60 + nums[2];
  return null;
}

function quantile(sortedVals, q) {
  if (sortedVals.length === 0) return null;
  if (sortedVals.length === 1) return sortedVals[0];
  const pos = (sortedVals.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sortedVals[lo];
  return sortedVals[lo] + (sortedVals[hi] - sortedVals[lo]) * (pos - lo);
}

// ---------------------------------------------------------------------------
// Dates & seasonality
// ---------------------------------------------------------------------------
const SEASON_WINDOW = 3;       // +/- weeks around the target's calendar week
const SEASON_MIN_SAMPLES = 5;  // below this, fall back to all events

// Next upcoming Saturday (today counts if today is Saturday).
function nextSaturday(from = new Date()) {
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  const delta = (6 - d.getDay() + 7) % 7; // 6 = Saturday
  d.setDate(d.getDate() + delta);
  return d;
}

function toISODate(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

// ISO 8601 week number (1..53) for a JS Date, matching Python's isocalendar().
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;          // Mon=1..Sun=7
  t.setUTCDate(t.getUTCDate() + 4 - day);  // nearest Thursday
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
}

// Circular distance between two ISO weeks on a ~52-week year.
function weekDistance(a, b) {
  const raw = Math.abs(a - b);
  return Math.min(raw, 53 - raw);
}

// ---------------------------------------------------------------------------
// Weather adjustment (v2) — OPTIONAL enhancement, used only when online and the
// target is within forecast range. The core app never depends on it.
//
// Chain (all measured per event, baked into the data):
//   forecast rain/wind  ->  deviation from this week's historical norm
//                       ->  estimated field-size change (event's own slope)
//                       ->  time adjustment (event's seconds-per-runner)
// Events whose data shows no weather effect (e.g. Crane) self-calibrate to ~0,
// so the adjustment is naturally negligible there.
// ---------------------------------------------------------------------------
const WEATHER_MAX_DAYS = 7;        // forecasts beyond ~a week aren't reliable
const WEATHER_DAMP = 0.6;          // conservative: don't overcorrect from a noisy signal
const WEATHER_MAX_SECONDS = 180;   // hard cap on the time shift (3:00), either way
const WEATHER_WINDY_FALLBACK = 20; // km/h, if the data didn't specify a threshold
const WEATHER_COMBO_BUMP = 0.25;   // wet+windy = stronger slope + this × weaker slope

function daysUntil(targetDate, from = new Date()) {
  const a = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  const b = new Date(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate());
  return Math.round((b - a) / 86400000);
}

function weatherEligible(targetDate) {
  const d = daysUntil(targetDate);
  return d >= 0 && d <= WEATHER_MAX_DAYS;
}

// Fetch 9am forecast (precip mm, wind km/h) for a date at given coords.
// Times out quickly so an offline predict never hangs the UI.
async function fetchForecast(lat, lon, isoDate) {
  const params = new URLSearchParams({
    latitude: lat, longitude: lon,
    hourly: "precipitation,wind_speed_10m",
    start_date: isoDate, end_date: isoDate,
    timezone: "Europe/London",
  });
  const url = `https://api.open-meteo.com/v1/forecast?${params}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  let res;
  try {
    res = await fetch(url, { cache: "no-store", signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new Error(`forecast: ${res.status}`);
  const data = await res.json();
  const times = data.hourly.time;
  const idx = times.findIndex((t) => t.endsWith("T09:00"));
  if (idx < 0) throw new Error("no 9am forecast");
  return {
    precip_mm: data.hourly.precipitation[idx],
    wind_kmh: data.hourly.wind_speed_10m[idx],
  };
}

// Resolve which weather slope (seconds-per-place) applies, given the forecast.
// Returns { slope, reasons } where slope is the per-place time penalty.
//
// Bad weather thins the field from the back, so the penalty scales with the
// target position: we store a per-event slope (s/place) for wet and for windy.
// If BOTH apply we don't just add them (the people who skip for rain largely
// overlap with those who skip for wind) — we take the stronger slope plus a
// small fraction of the weaker.
function resolveWeatherSlope(event, targetWeek, forecast) {
  const w = event.weather;
  if (!w || !forecast) return { slope: 0, reasons: [] };
  const norm = w.week_norm[String(targetWeek)];
  if (!norm) return { slope: 0, reasons: [] };

  const sens = w.sensitivity;
  const windyThreshold = w.windy_threshold_kmh || WEATHER_WINDY_FALLBACK;

  const forecastWet = forecast.precip_mm > 0;
  const forecastWindy = forecast.wind_kmh >= windyThreshold;
  // Only count a condition if it deviates from what's normal for this week
  // (a normally-wet week is already in the seasonal baseline).
  const normallyWet = norm.precip_mm > 0;
  const normallyWindy = norm.wind_kmh >= windyThreshold;

  const slopes = [];
  const reasons = [];
  if (forecastWet && !normallyWet && sens.wet_slope > 0) {
    slopes.push(sens.wet_slope);
    reasons.push("rain");
  }
  if (forecastWindy && !normallyWindy && sens.windy_slope > 0) {
    slopes.push(sens.windy_slope);
    reasons.push("strong wind");
  }

  let slope = 0;
  if (slopes.length === 1) {
    slope = slopes[0];
  } else if (slopes.length === 2) {
    const stronger = Math.max(...slopes);
    const weaker = Math.min(...slopes);
    slope = stronger + WEATHER_COMBO_BUMP * weaker;   // option 2: max + a bump
  }
  return { slope, reasons };
}

// The time adjustment (seconds; + = aim slower) for a specific target position.
function weatherSecondsForPosition(slopeInfo, position) {
  const raw = slopeInfo.slope * position * WEATHER_DAMP;
  return clamp(raw, -WEATHER_MAX_SECONDS, WEATHER_MAX_SECONDS);
}

function clamp(x, lo, hi) {
  return Math.max(lo, Math.min(hi, x));
}

// ---------------------------------------------------------------------------
// Data loading
//
// Prefers the bundled data (window.PBP_DATA, from app/data.js) so the app can
// run straight from file:// with no server. Falls back to fetch() when the
// bundle isn't present (e.g. a trimmed deployment served over http).
// ---------------------------------------------------------------------------
function hasBundle() {
  return typeof window !== "undefined" && window.PBP_DATA
    && window.PBP_DATA.manifest && window.PBP_DATA.events;
}

async function loadJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function getManifest() {
  if (hasBundle()) return window.PBP_DATA.manifest;
  return loadJSON("data/manifest.json");
}

async function getEventData(slug) {
  if (hasBundle()) {
    const ev = window.PBP_DATA.events[slug];
    if (ev) return ev;
  }
  return loadJSON(`data/${slug}.json`);
}

// ---------------------------------------------------------------------------
// Data refresh — fetch a fresh data bundle from the network, bypassing caches,
// so you can pull in a rebuild without reinstalling. Reports what happened in a
// quiet status line (no popups).
// ---------------------------------------------------------------------------
let refreshing = false;

// Total events across all events in the current bundle (used to detect change).
function totalEvents(bundle) {
  if (!bundle || !bundle.events) return 0;
  return Object.values(bundle.events)
    .reduce((sum, ev) => sum + (ev.event_count || 0), 0);
}

const LAST_UPDATED_KEY = "pbp:lastUpdated";

// Format a timestamp as "DD/MM/YYYY at HH:MM".
function fmtLastUpdated(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} `
    + `at ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function getLastUpdated() {
  try {
    const v = localStorage.getItem(LAST_UPDATED_KEY);
    return v ? Number(v) : null;
  } catch (e) { return null; }
}

function setLastUpdated(ts) {
  try { localStorage.setItem(LAST_UPDATED_KEY, String(ts)); } catch (e) { /* ignore */ }
}

// Show a transient refresh message. When msg is empty, fall back to the
// permanent "Last updated on ..." line (if we have a timestamp).
function setRefreshStatus(msg) {
  const el = document.getElementById("refresh-status");
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.classList.add("show");
    return;
  }
  const ts = getLastUpdated();
  if (ts) {
    el.textContent = `Last updated on ${fmtLastUpdated(ts)}`;
    el.classList.add("show");
  } else {
    el.textContent = "";
    el.classList.remove("show");
  }
}

async function refreshData() {
  if (refreshing) return;
  refreshing = true;
  setRefreshStatus("Checking for data updates\u2026");

  const before = totalEvents(window.PBP_DATA);
  try {
    // Cache-bust so we bypass both the browser and service-worker caches.
    const res = await fetch(`data.js?ts=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`data.js: ${res.status}`);
    const text = await res.text();

    // data.js is "window.PBP_DATA = {...};" — evaluate it to refresh the global.
    // It's our own first-party file fetched same-origin, not third-party input.
    new Function(text)();
    const after = totalEvents(window.PBP_DATA);

    // Rebuild the event dropdown + reload the current event from the new data.
    state.manifest = window.PBP_DATA.manifest;
    repopulateEvents();
    const slug = state.slug && window.PBP_DATA.events[state.slug]
      ? state.slug : state.manifest.events[0].slug;
    document.getElementById("event-select").value = slug;
    await selectEvent(slug);

    // Ask the service worker to refresh its cached copy too (installed PWA).
    if ("serviceWorker" in navigator && navigator.serviceWorker.controller) {
      navigator.serviceWorker.getRegistration().then((r) => r && r.update());
    }

    // A successful fetch means the on-screen data is current as of now.
    setLastUpdated(Date.now());

    if (after > before) {
      setRefreshStatus(`Data refreshed \u00b7 now ${after} events (was ${before}).`);
    } else {
      setRefreshStatus("Already up to date.");
    }
  } catch (e) {
    setRefreshStatus("Couldn't reach the server \u2014 still using saved data.");
  } finally {
    refreshing = false;
    // After a pause, replace the transient message with the permanent
    // "Last updated on ..." line.
    setTimeout(() => setRefreshStatus(""), 8000);
  }
}

// Re-fill the event <select> from the current manifest (after a refresh).
function repopulateEvents() {
  const sel = document.getElementById("event-select");
  const current = sel.value;
  sel.innerHTML = "";
  for (const ev of state.manifest.events) {
    const opt = document.createElement("option");
    opt.value = ev.slug;
    opt.textContent = ev.name;
    sel.appendChild(opt);
  }
  if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

// Running as the installed PWA (standalone)? Used to hide the laptop-only button.
function isStandalone() {
  return window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;
}

async function init() {
  try {
    state.manifest = await getManifest();
  } catch (e) {
    showFatal(
      "Couldn't load the data. Run the collector (python3 collector/build.py) " +
      "to regenerate app/data.js, then reopen this page."
    );
    return;
  }

  const sel = document.getElementById("event-select");
  sel.innerHTML = "";
  for (const ev of state.manifest.events) {
    const opt = document.createElement("option");
    opt.value = ev.slug;
    opt.textContent = ev.name;
    sel.appendChild(opt);
  }
  sel.addEventListener("change", () => selectEvent(sel.value));

  buildGrid();
  wireControls();
  initDate();
  initRefresh();

  // Restore the one shared card + setup (migrating any old per-event data).
  const saved = loadSaved();
  if (saved) applySaved(saved);
  else markSaved(null);

  // Seed the "last updated" time on first ever load (the bundle just loaded),
  // then show the permanent "Last updated on ..." line.
  if (getLastUpdated() == null) setLastUpdated(Date.now());
  setRefreshStatus("");

  if (state.manifest.events.length) {
    await selectEvent(state.manifest.events[0].slug);
  } else {
    showFatal("No events in the manifest yet. Add saved results pages and rebuild.");
  }
}

async function selectEvent(slug) {
  state.event = await getEventData(slug);
  state.slug = slug;

  // The card (needed numbers + setup) is global and shared across events, so
  // switching events deliberately leaves it untouched — we only swap which
  // event's historical data we predict against.

  const meta = state.manifest.events.find((e) => e.slug === slug);
  const rng = meta.date_range || [];
  const span = rng.length === 2
    ? (rng[0] === rng[1] ? rng[0] : `${rng[0]} \u2192 ${rng[1]}`)
    : "no dates";
  const metaEl = document.getElementById("event-meta");
  let text = `${meta.event_count} event(s) \u00b7 ${span} \u00b7 field up to ${meta.max_position}`;
  // Caveat for thin datasets (< ~1 year): predictions are rough and seasonal /
  // weather features won't have enough data to kick in.
  metaEl.classList.toggle("sparse", meta.event_count < 52);
  if (meta.event_count < 52) {
    text += ` \u2014 early data, predictions are rough and will sharpen as more `
      + `weeks are added`;
  }
  metaEl.textContent = text;
  document.getElementById("data-note").textContent =
    `Data: ${meta.name}, ${meta.event_count} event(s) parsed.`;
}

// ---------------------------------------------------------------------------
// Bingo grid
// ---------------------------------------------------------------------------
function buildGrid() {
  const grid = document.getElementById("bingo-grid");
  grid.innerHTML = "";
  for (let n = 0; n < 100; n++) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "bingo-cell";
    cell.textContent = pad2(n);
    cell.setAttribute("aria-pressed", "false");
    cell.dataset.n = String(n);
    cell.addEventListener("click", () => toggleCell(n, cell));
    grid.appendChild(cell);
  }
  updateNeedCount();
}

function toggleCell(n, cell) {
  if (state.needed.has(n)) {
    state.needed.delete(n);
    cell.classList.remove("needed");
    cell.setAttribute("aria-pressed", "false");
  } else {
    state.needed.add(n);
    cell.classList.add("needed");
    cell.setAttribute("aria-pressed", "true");
  }
  updateNeedCount();
  saveState();
}

function setAll(on) {
  setNeeded(on ? new Set(Array.from({ length: 100 }, (_, i) => i)) : new Set());
  saveState();
}

// Set the full "needed" selection and sync the grid UI to match. Does not save
// (callers decide), so it's reusable for both user actions and restoring.
function setNeeded(set) {
  state.needed = set;
  for (const cell of document.querySelectorAll(".bingo-cell")) {
    const on = state.needed.has(Number(cell.dataset.n));
    cell.classList.toggle("needed", on);
    cell.setAttribute("aria-pressed", String(on));
  }
  updateNeedCount();
}

function updateNeedCount() {
  document.getElementById("need-count").textContent =
    `${state.needed.size} number(s) selected`;
}

// ---------------------------------------------------------------------------
// Prediction
// ---------------------------------------------------------------------------
// For a bingo number N, candidate finishing positions are N, N+100, N+200 ...
// but position 0 isn't real, so for N===0 the first candidate is 100.
function candidatePositions(n, maxPos) {
  const out = [];
  let p = n === 0 ? 100 : n;
  while (p <= maxPos) {
    out.push(p);
    p += 100;
  }
  return out;
}

const VOLATILITY_LABEL = {
  low: "Low",
  medium: "Medium",
  high: "High",
  "low-data": "Not enough data",
  single: "One event only",
};

// Pre-computed all-time stats for an exact position (from the aggregator).
function statsForPosition(pos) {
  const entry = state.event.positions[String(pos)];
  return entry && entry.stats ? entry.stats : null;
}

// Pre-computed seasonal (+/-3 week) band for a position at a given ISO week, or
// null if that week has no coverage. Stored compactly as [n, p25, p50, p75];
// we expand it to a stats-like object, deriving iqr/volatility and borrowing
// min/max from the all-time stats (good enough for display).
function seasonalStatsForPosition(pos, week) {
  const entry = state.event.positions[String(pos)];
  if (!entry || !entry.seasonal) return null;
  const a = entry.seasonal[String(week)];
  if (!a) return null;
  const [n, p25, p50, p75] = a;
  const iqr = p75 - p25;
  let volatility;
  if (n < 2) volatility = "single";
  else if (n < 3) volatility = "low-data";
  else {
    const cv = p50 ? iqr / p50 : 0;
    volatility = cv < 0.04 ? "low" : cv < 0.09 ? "medium" : "high";
  }
  const base = entry.stats || {};
  return {
    n, p25, p50, p75, iqr, volatility,
    min: base.min != null ? base.min : p25,
    max: base.max != null ? base.max : p75,
  };
}

// Nearest-neighbour fallback: average of surrounding positions' all-time stats,
// for positions that have no data of their own. Returns a stats-like object.
function nearbyStats(pos, window = 2) {
  for (let w = 1; w <= window; w++) {
    const picks = [];
    for (const p of [pos - w, pos + w]) {
      const st = statsForPosition(p);
      if (st) picks.push(st);
    }
    if (picks.length) {
      const avg = (k) => Math.round(picks.reduce((s, x) => s + x[k], 0) / picks.length);
      return {
        p25: avg("p25"), p50: avg("p50"), p75: avg("p75"),
        min: avg("min"), max: avg("max"),
        iqr: avg("iqr"), n: 0, volatility: "low-data",
      };
    }
  }
  return null;
}

function bandFromStats(st, basis, exact) {
  return {
    lo: st.p25, hi: st.p75, median: st.p50,
    min: st.min, max: st.max,
    samples: st.n, iqr: st.iqr, volatility: st.volatility,
    exact, basis,
  };
}

// Shift every time in a band by `seconds` (weather adjustment). Volatility and
// sample count are unchanged — we're moving the whole distribution, not
// reshaping it.
function shiftBand(band, seconds) {
  return {
    ...band,
    lo: band.lo + seconds,
    hi: band.hi + seconds,
    median: band.median + seconds,
    min: band.min + seconds,
    max: band.max + seconds,
    weatherShift: seconds,
  };
}

// Build the aim band + volatility for a single candidate position, honouring
// the seasonal setting. opts: { season: bool, week: int }.
function rangeForPosition(pos, opts) {
  const allTime = statsForPosition(pos);

  if (allTime) {
    if (opts.season) {
      const seasonal = seasonalStatsForPosition(pos, opts.week);
      // Use the seasonal band if it has enough samples; else fall back to
      // all-time (and say so).
      if (seasonal && seasonal.n >= SEASON_MIN_SAMPLES) {
        return bandFromStats(seasonal, "season", true);
      }
      return bandFromStats(allTime, "all-fallback", true);
    }
    return bandFromStats(allTime, "all", true);
  }

  // No data for this exact position: estimate from nearby positions.
  const st = nearbyStats(pos);
  if (!st) return null;
  return { ...bandFromStats(st, "nearby", false), volatility: "low-data" };
}

async function predict() {
  const results = document.getElementById("results");
  const body = document.getElementById("results-body");
  body.innerHTML = "";

  if (!state.event) return;

  // Echo the selected event in the results heading.
  const meta = state.manifest.events.find((e) => e.slug === state.slug);
  const eventName = meta ? meta.name : state.slug;
  document.getElementById("results-title").textContent =
    `Target times for ${eventName}`;

  if (state.needed.size === 0) {
    body.innerHTML = `<p class="empty">Select the numbers you still need above.</p>`;
    results.hidden = false;
    return;
  }

  // Edge case: every bingo number still needed. Any finishing position ticks
  // something, so per-position targets are meaningless — just reassure.
  if (state.needed.size >= 100) {
    body.innerHTML =
      `<div class="bestbet-card">`
      + `<div class="bestbet-title">You need every number</div>`
      + `<div class="bestbet-headline">Just run \u2014 any finishing position `
      + `ticks one of your numbers, so you're guaranteed a tick as long as you `
      + `finish. Run whatever time you fancy!</div>`
      + `</div>`;
    results.hidden = false;
    results.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  const maxPos = state.event.max_position;
  const paceMin = parseTime(document.getElementById("pace-min").value); // faster bound (seconds)
  const paceMax = parseTime(document.getElementById("pace-max").value); // slower bound

  // Seasonal context
  const useSeason = document.getElementById("use-season").checked;
  const dateVal = document.getElementById("target-date").value;
  const targetDate = dateVal ? new Date(dateVal + "T00:00:00") : nextSaturday();
  const targetWeek = isoWeek(targetDate);
  const opts = { season: useSeason, week: targetWeek };

  // Render immediately from cached data (NEVER blocks on the network), then
  // fetch the forecast in the background and re-render with the weather
  // adjustment only if/when it arrives. This keeps the app instant offline —
  // the weather is an enhancement, never a prerequisite.
  renderResults({ state: "pending" });

  if (document.getElementById("use-weather").checked
      && state.event.weather && meta && meta.lat != null && weatherEligible(targetDate)) {
    resolveWeather(meta, targetDate, targetWeek)
      .then((weather) => {
        // Re-render with the adjustment (or a muted "no adjustment" note).
        if (weather.state === "ok" || weather.state === "offline") {
          renderResults(weather);
        }
      })
      .catch(() => { /* keep the already-rendered cached result */ });
  }

  // ---- the full render, as a closure so it can run now (cached) and again
  //      later (with weather) against the same inputs ----
  function renderResults(weather) {
  body.innerHTML = "";
  document.getElementById("results-title").textContent =
    `Target times for ${eventName}`;
  const weatherActive = weather && weather.state === "ok"
    && weather.slopeInfo && weather.slopeInfo.slope > 0;

  const numbers = Array.from(state.needed).sort((a, b) => a - b);
  let anyShown = false;
  let anyFallback = false;

  // First pass: compute qualifying rows for every needed number, and collect a
  // flat list of all candidate targets so we can pick the single best bet.
  const rowsByNumber = new Map();
  const allCandidates = []; // { n, pos, band }
  for (const n of numbers) {
    const positions = candidatePositions(n, maxPos);
    const rows = [];
    for (const pos of positions) {
      let band = rangeForPosition(pos, opts);
      if (!band) continue;
      if (band.basis === "all-fallback") anyFallback = true;
      if (weatherActive) {
        const shift = weatherSecondsForPosition(weather.slopeInfo, pos);
        if (Math.abs(shift) >= 3) band = shiftBand(band, shift);
      }
      // Pace filter on the (possibly weather-adjusted) times.
      if (paceMin != null && band.median < paceMin) continue;
      if (paceMax != null && band.median > paceMax) continue;
      rows.push({ pos, band });
      allCandidates.push({ n, pos, band });
    }
    rowsByNumber.set(n, rows);
  }

  // Top few best bets at the very top, then the seasonal context banner.
  const topBets = rankBestBets(allCandidates, paceMin, paceMax, 3);
  const bestOpp = pickBestOpportunity(allCandidates, state.needed, maxPos, opts);
  renderBestBetSummary(body, topBets, { paceMin, paceMax });
  renderOdds(body, state.needed.size);
  renderOpportunity(body, bestOpp);
  renderSeasonBanner(body, useSeason, targetDate);
  renderWeatherBanner(body, weather);

  // Second pass: render the per-number detail list.
  for (const n of numbers) {
    const rows = rowsByNumber.get(n);

    const item = document.createElement("div");
    item.className = "results-item";
    const head = document.createElement("h3");
    head.innerHTML = `<span class="pill">${pad2(n)}</span> finish to tick this`;
    item.appendChild(head);

    if (!rows.length) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = paceMin != null || paceMax != null
        ? "No positions for this number fall within your pace range."
        : "No historical data for the positions that would tick this number.";
      item.appendChild(p);
    } else {
      anyShown = true;

      // "Best bet" = the position you can most reliably hit: lowest volatility,
      // tie-broken by narrowest IQR. Only meaningful with real volatility data.
      const rank = { low: 0, medium: 1, high: 2, "low-data": 3, single: 4 };
      let best = null;
      for (const r of rows) {
        const vr = rank[r.band.volatility] ?? 5;
        const iqr = r.band.iqr ?? Infinity;
        if (!best || vr < best.vr || (vr === best.vr && iqr < best.iqr)) {
          best = { pos: r.pos, vr, iqr };
        }
      }

      for (const { pos, band } of rows) {
        const row = document.createElement("div");
        row.className = "target-row";

        const left = document.createElement("div");
        left.className = "target-pos";
        const isBest = best && pos === best.pos && rows.length > 1
          && (band.volatility === "low" || band.volatility === "medium");
        const basisTxt = {
          season: "seasonal",
          "all-fallback": "all year (too few nearby weeks)",
          all: "all year",
          nearby: "nearby positions",
        }[band.basis] || "";
        left.innerHTML =
          `<span class="pos-label">Finish ${pos}</span>` +
          (isBest ? ` <span class="best-bet">best bet</span>` : "") +
          `<span class="pos-sub">${band.samples} event${band.samples === 1 ? "" : "s"}` +
          `${basisTxt ? ` \u00b7 ${basisTxt}` : ""}</span>`;

        const right = document.createElement("div");
        right.className = "target-time";
        const bandTxt = band.lo === band.hi
          ? fmtTime(band.median)
          : `${fmtTime(band.lo)}\u2013${fmtTime(band.hi)}`;
        const fullTxt = band.min === band.max
          ? ""
          : `<span class="full-range">full ${fmtTime(band.min)}\u2013${fmtTime(band.max)}</span>`;
        const vLabel = VOLATILITY_LABEL[band.volatility] || band.volatility;
        const vClass = ["low", "medium", "high"].includes(band.volatility)
          ? band.volatility : "unknown";
        const swing = band.iqr != null && band.iqr > 0
          ? ` \u00b1${fmtTime(band.iqr)}` : "";
        right.innerHTML =
          `<span class="aim">${bandTxt}</span>` +
          `<span class="aim-sub">aim ${fmtTime(band.median)}</span>` +
          fullTxt +
          `<span class="vol vol-${vClass}">${vLabel}${swing}</span>`;

        row.appendChild(left);
        row.appendChild(right);
        item.appendChild(row);
      }
    }
    body.appendChild(item);
  }

  if (!anyShown && (paceMin != null || paceMax != null)) {
    const note = document.createElement("p");
    note.className = "meta";
    note.textContent = "Tip: widen your pace range to see more options.";
    body.appendChild(note);
  }

  if (anyFallback) {
    const note = document.createElement("p");
    note.className = "meta";
    note.textContent =
      "Some positions didn't have enough data near this time of year, so they " +
      "fall back to the whole-year picture. More weeks of data will sharpen these.";
    body.appendChild(note);
  }

  results.hidden = false;
  }  // end renderResults

  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Lower = more reliable. Shared by the per-number best and the overall summary.
const VOLATILITY_RANK = { low: 0, medium: 1, high: 2, "low-data": 3, single: 4 };

// Pick the single most reliable target across all needed numbers.
// Criteria, in order:
//   1. lowest volatility,
//   2. narrowest aim band (IQR),
//   3. closest to the middle of the user's pace range (most comfortably
//      achievable, not right at the edge of their ability).
// Returns the top `limit` targets overall, best first. A bingo number may
// appear more than once (e.g. finish 22nd and 122nd both tick 22) if those are
// among the most reliable targets. Empty array if no candidates.
function rankBestBets(candidates, paceMin, paceMax, limit = 3) {
  if (!candidates.length) return [];
  const mid = (paceMin != null && paceMax != null)
    ? (paceMin + paceMax) / 2 : null;

  const score = (c) => ({
    vr: VOLATILITY_RANK[c.band.volatility] ?? 5,
    iqr: c.band.iqr ?? Infinity,
    distMid: mid != null ? Math.abs(c.band.median - mid) : 0,
  });
  const cmp = (a, b) => {
    const ka = score(a), kb = score(b);
    return (ka.vr - kb.vr) || (ka.iqr - kb.iqr) || (ka.distMid - kb.distMid);
  };

  return candidates.slice().sort(cmp).slice(0, limit);
}

// ---------------------------------------------------------------------------
// Opportunity mode — "best chance of ticking ANYTHING you need"
//
// A target finish time doesn't land you on one position; across events it maps
// to a spread of positions. If your needed numbers cluster together, aiming at
// the middle of a cluster means even if you drift a few places you still tick
// *something*. We score each candidate target by what share of its plausible
// finishing positions land on a still-needed bingo cell (pos mod 100), which is
// effectively "probability this run ticks a number you need".
// ---------------------------------------------------------------------------

// Median finish time at a position, honouring the seasonal setting. Cached per
// predict() run via the passed memo map.
function medianAtPosition(pos, opts, memo) {
  if (memo.has(pos)) return memo.get(pos);
  let val = null;
  if (opts.season) {
    const seasonal = seasonalStatsForPosition(pos, opts.week);
    if (seasonal && seasonal.n >= SEASON_MIN_SAMPLES) {
      val = seasonal.p50;
    } else {
      const all = statsForPosition(pos);
      val = all ? all.p50 : null;
    }
  } else {
    const all = statsForPosition(pos);
    val = all ? all.p50 : null;
  }
  memo.set(pos, val);
  return val;
}

// Positions whose median time falls within [loT, hiT] — i.e. the finishing
// positions you'd plausibly land on when aiming at that time window.
function positionsInTimeBand(loT, hiT, maxPos, opts, memo) {
  const out = [];
  for (let p = 1; p <= maxPos; p++) {
    const m = medianAtPosition(p, opts, memo);
    if (m != null && m >= loT && m <= hiT) out.push(p);
  }
  return out;
}

// Score a candidate target by how many of its plausible positions tick a needed
// number. Returns { prob, coveredCells:Set, spread:[lo,hi], positions:int }.
function opportunityScore(band, neededSet, maxPos, opts, memo) {
  const plausible = positionsInTimeBand(band.lo, band.hi, maxPos, opts, memo);
  if (!plausible.length) return { prob: 0, coveredCells: new Set(), spread: null, positions: 0 };
  let hits = 0;
  const covered = new Set();
  for (const p of plausible) {
    const cell = p % 100;            // wraps: 100 -> 0, 101 -> 1, etc.
    if (neededSet.has(cell)) {
      hits++;
      covered.add(cell);
    }
  }
  return {
    prob: hits / plausible.length,
    coveredCells: covered,
    spread: [plausible[0], plausible[plausible.length - 1]],
    positions: plausible.length,
  };
}

// Pick the single best opportunity target: highest hit-probability, tiebroken
// by number of distinct needed cells covered, then reliability. We evaluate one
// representative candidate per needed position (the candidates already built).
function pickBestOpportunity(candidates, neededSet, maxPos, opts) {
  if (!candidates.length) return null;
  const memo = new Map();
  let best = null;
  for (const c of candidates) {
    const sc = opportunityScore(c.band, neededSet, maxPos, opts, memo);
    if (sc.positions === 0) continue;
    const vr = VOLATILITY_RANK[c.band.volatility] ?? 5;
    const key = { prob: sc.prob, nCells: sc.coveredCells.size, vr };
    if (!best) { best = { ...c, sc, key }; continue; }
    const b = best.key;
    if (
      key.prob > b.prob ||
      (key.prob === b.prob && key.nCells > b.nCells) ||
      (key.prob === b.prob && key.nCells === b.nCells && key.vr < b.vr)
    ) {
      best = { ...c, sc, key };
    }
  }
  return best;
}

function bandText(band) {
  return band.lo === band.hi
    ? fmtTime(band.median)
    : `${fmtTime(band.lo)}\u2013${fmtTime(band.hi)}`;
}

function volHtml(band) {
  const vLabel = VOLATILITY_LABEL[band.volatility] || band.volatility;
  const vClass = ["low", "medium", "high"].includes(band.volatility)
    ? band.volatility : "unknown";
  const swing = band.iqr != null && band.iqr > 0 ? ` \u00b1${fmtTime(band.iqr)}` : "";
  return `<span class="vol vol-${vClass}">${vLabel}${swing}</span>`;
}

// Render the "best bets" summary card (top few targets) above the detail list.
function renderBestBetSummary(body, bets, { paceMin, paceMax }) {
  const card = document.createElement("div");
  card.className = "bestbet-card";

  if (!bets.length) {
    card.classList.add("bestbet-empty");
    const hasPace = paceMin != null || paceMax != null;
    card.innerHTML =
      `<div class="bestbet-title">No clear best bet</div>` +
      `<div class="bestbet-detail">` +
      (hasPace
        ? "Nothing matched your pace range. Try widening the fastest/slowest times."
        : "No historical data for the positions that would tick your numbers.") +
      `</div>`;
    body.appendChild(card);
    return;
  }

  // Headline: the single best.
  const top = bets[0];
  let html =
    `<div class="bestbet-title">Your best bet${bets.length > 1 ? "s" : ""}</div>` +
    `<div class="bestbet-headline">` +
      `Aim for <strong>${fmtTime(top.band.median)}</strong> ` +
      `to finish around <strong>${top.pos}</strong> ` +
      `and tick <span class="pill">${pad2(top.n)}</span>` +
    `</div>` +
    `<div class="bestbet-detail">` +
      `Target range ${bandText(top.band)} ${volHtml(top.band)} ` +
      `\u00b7 based on ${top.band.samples} event${top.band.samples === 1 ? "" : "s"}` +
      `${top.band.basis === "season" ? " near this time of year" : ""}` +
    `</div>`;

  // Runners-up (up to two more), as a compact ranked list.
  if (bets.length > 1) {
    html += `<ol class="bestbet-list">`;
    for (let i = 1; i < bets.length; i++) {
      const b = bets[i];
      html +=
        `<li>` +
          `<span class="bb-pill pill">${pad2(b.n)}</span>` +
          `<span class="bb-time">${fmtTime(b.band.median)}</span>` +
          `<span class="bb-pos">~${b.pos}</span>` +
          `<span class="bb-range">${bandText(b.band)}</span>` +
          volHtml(b.band) +
        `</li>`;
    }
    html += `</ol>`;
  }

  card.innerHTML = html;
  body.appendChild(card);
}

// Render an honest estimate of this week's odds: the chance of ticking a needed
// number if you aim at the best target, vs just turning up (baseline ~k/100).
// The aimed figure comes from a build-time simulation over the event's real
// history (odds_by_k), which captures genuine week-to-week scatter.
function renderOdds(body, neededCount) {
  const curve = state.event.odds_by_k;
  if (!curve) return;
  const aimed = curve[String(neededCount)];
  if (aimed == null || aimed <= 0) return;

  const baseline = neededCount / 100;
  const pct = (x) => `${Math.round(x * 100)}%`;
  const lift = baseline > 0 ? aimed / baseline : 0;
  const liftTxt = lift >= 1.15
    ? ` \u2014 about ${lift.toFixed(1)}\u00d7 better than just turning up` : "";

  const card = document.createElement("div");
  card.className = "odds-card";
  card.innerHTML =
    `<span class="odds-big">${pct(aimed)}</span>`
    + `<span class="odds-text">estimated chance of ticking one of your `
    + `${neededCount} number${neededCount === 1 ? "" : "s"} this week if you aim `
    + `at the best target<span class="odds-sub">vs ~${pct(baseline)} just `
    + `turning up${liftTxt}</span></span>`;
  body.appendChild(card);
}

// Render the "best chance of ticking anything" opportunity callout.
function renderOpportunity(body, opp) {
  // Only worth showing when it meaningfully beats a single-number dart, i.e.
  // its plausible finish spread overlaps more than one needed cell.
  if (!opp || opp.sc.coveredCells.size < 2) return;

  const cells = Array.from(opp.sc.coveredCells).sort((a, b) => a - b).map(pad2);
  const pct = Math.round(opp.sc.prob * 100);
  const [slo, shi] = opp.sc.spread;

  const card = document.createElement("div");
  card.className = "opp-card";
  card.innerHTML =
    `<div class="opp-title">Best chance of ticking something</div>` +
    `<div class="opp-headline">` +
      `Aim for <strong>${fmtTime(opp.band.median)}</strong> ` +
      `(finish ~${slo}\u2013${shi})` +
    `</div>` +
    `<div class="opp-detail">` +
      `Could tick ${cells.map((c) => `<span class="pill">${c}</span>`).join(" ")} ` +
      `\u2014 about ${pct}% of likely finishes here land on one of your numbers.` +
    `</div>`;
  body.appendChild(card);
}

// Resolve the weather adjustment for this prediction. Returns an object
// describing the outcome (for the banner) — never throws. Shapes:
//   { state: "off" }                         toggle off
//   { state: "out-of-range" }                target >7 days away or in the past
//   { state: "no-data" }                     event has no weather model
//   { state: "offline" }                     fetch failed / offline
//   { state: "ok", adj: {...} }              adjustment computed (may be ~0)
async function resolveWeather(meta, targetDate, targetWeek) {
  if (!document.getElementById("use-weather").checked) return { state: "off" };
  if (!state.event.weather) return { state: "no-data" };
  if (!meta || meta.lat == null || meta.lon == null) return { state: "no-data" };
  if (!weatherEligible(targetDate)) return { state: "out-of-range" };

  try {
    const forecast = await fetchForecast(meta.lat, meta.lon, toISODate(targetDate));
    const slopeInfo = resolveWeatherSlope(state.event, targetWeek, forecast);
    return { state: "ok", forecast, slopeInfo };
  } catch (e) {
    return { state: "offline" };
  }
}

// Render the weather banner describing what (if anything) was applied.
// "pending" = the instant cached render before the forecast has come back; show
// nothing (the re-render will add the banner if the forecast arrives).
function renderWeatherBanner(body, weather) {
  if (!weather || weather.state === "off" || weather.state === "pending") return;

  const banner = document.createElement("p");
  banner.className = "weather-banner";

  if (weather.state === "out-of-range") {
    banner.classList.add("weather-muted");
    banner.textContent =
      "Weather adjustment applies only within a week of the date \u2014 showing the "
      + "usual seasonal prediction.";
    body.appendChild(banner);
    return;
  }
  if (weather.state === "no-data") {
    // Event simply has no weather model; stay quiet rather than nag.
    return;
  }
  if (weather.state === "offline") {
    banner.classList.add("weather-muted");
    banner.textContent =
      "Couldn't fetch the forecast (offline?) \u2014 showing the usual seasonal "
      + "prediction, no weather adjustment.";
    body.appendChild(banner);
    return;
  }

  // state === "ok" — always surface the actual forecast, with an icon, then
  // note any adjustment separately.
  const fc = weather.forecast;
  const si = weather.slopeInfo;
  const wet = fc.precip_mm > 0;
  const windyThreshold =
    (state.event.weather && state.event.weather.windy_threshold_kmh) || 20;
  const windy = fc.wind_kmh >= windyThreshold;

  // Pick a representative icon.
  let icon = "\u2600\uFE0F";          // sun
  if (wet && windy) icon = "\uD83C\uDF27\uFE0F";   // cloud with rain
  else if (wet) icon = "\uD83C\uDF26\uFE0F";       // sun behind rain
  else if (windy) icon = "\uD83D\uDCA8";           // dashing wind
  else if (fc.wind_kmh >= 12) icon = "\u26C5";     // breezy: sun behind cloud

  const precipTxt = wet ? `${fc.precip_mm.toFixed(1)} mm rain` : "dry";
  const windTxt = `${Math.round(fc.wind_kmh)} km/h wind`;

  const headline = document.createElement("div");
  headline.className = "weather-headline";
  headline.innerHTML =
    `<span class="weather-icon">${icon}</span>`
    + `<span>Forecast 9am: <strong>${precipTxt}</strong>, ${windTxt}</span>`;
  banner.appendChild(headline);

  const note = document.createElement("div");
  note.className = "weather-note";
  if (si && si.slope > 0 && si.reasons.length) {
    const egShift = weatherSecondsForPosition(si, 100);
    note.textContent =
      `${si.reasons.join(" & ")} tends to thin the field from the back here, so `
      + `deeper targets ease more \u2014 about +${fmtTime(egShift)} at ~100th, `
      + `more further back.`;
  } else {
    banner.classList.add("weather-muted");
    note.textContent = "Close to typical \u2014 no time adjustment applied.";
  }
  banner.appendChild(note);
  body.appendChild(banner);
}

// Banner at the top of results describing the seasonal basis used.
function renderSeasonBanner(body, useSeason, targetDate) {
  const banner = document.createElement("p");
  banner.className = "season-banner";
  const dStr = targetDate.toLocaleDateString(undefined, {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
  banner.textContent = useSeason
    ? `Targeting ${dStr} \u2014 weighted to events within \u00b13 weeks of that time of year.`
    : `Using all events across the year (seasonal weighting off).`;
  body.appendChild(banner);
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
function wireControls() {
  document.getElementById("select-all").addEventListener("click", () => setAll(true));
  document.getElementById("clear-all").addEventListener("click", () => setAll(false));
  document.getElementById("predict").addEventListener("click", predict);

  const onSetupChange = () => { updateSeasonMeta(); saveState(); };
  document.getElementById("target-date").addEventListener("change", onSetupChange);
  document.getElementById("use-season").addEventListener("change", onSetupChange);
  document.getElementById("use-weather").addEventListener("change", saveState);
  document.getElementById("pace-min").addEventListener("change", saveState);
  document.getElementById("pace-max").addEventListener("change", saveState);

  document.getElementById("reset-saved").addEventListener("click", resetSaved);

  // Info overlay. Visibility is driven by the .open class (see CSS) so it floats
  // above the app rather than pushing content down.
  const overlay = document.getElementById("info-overlay");
  const openInfo = () => { overlay.hidden = false; };
  const closeInfo = () => { overlay.hidden = true; };
  document.getElementById("info-btn").addEventListener("click", openInfo);
  document.getElementById("info-close").addEventListener("click", closeInfo);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeInfo(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) closeInfo();
  });
}

// Set up the refresh affordances: a laptop-only button (hidden in the installed
// PWA) and a pull-to-refresh gesture that works everywhere.
function initRefresh() {
  const btn = document.getElementById("refresh-data");
  if (btn) {
    // Show the button only when NOT running as the installed standalone PWA.
    if (!isStandalone()) btn.hidden = false;
    btn.addEventListener("click", refreshData);
  }
  initPullToRefresh();
}

// Pull-to-refresh: when scrolled to the very top, a downward drag past a
// threshold triggers a data refresh. Kept deliberately simple and only active
// at the top so it never fights normal scrolling.
function initPullToRefresh() {
  const indicator = document.getElementById("ptr-indicator");
  const THRESHOLD = 70;   // px of pull needed to trigger
  const MAX = 90;         // px the indicator travels
  let startY = null;
  let pulling = false;

  function atTop() {
    return (window.scrollY || document.documentElement.scrollTop || 0) <= 0;
  }

  window.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || !atTop() || refreshing) { startY = null; return; }
    startY = e.touches[0].clientY;
    pulling = false;
  }, { passive: true });

  window.addEventListener("touchmove", (e) => {
    if (startY === null) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0) { reset(); return; }
    // Only engage if we're still at the top of the page.
    if (!atTop()) { reset(); return; }
    pulling = true;
    const travel = Math.min(dy, MAX);
    indicator.style.transform = `translateY(${travel}px)`;
    indicator.classList.add("visible");
    // Subtle symbol cue only (no redundant text): arrow, tick past threshold.
    indicator.textContent = dy >= THRESHOLD ? "\u2713" : "\u2193";
  }, { passive: true });

  window.addEventListener("touchend", (e) => {
    if (!pulling) { reset(); return; }
    const dy = (e.changedTouches[0].clientY - (startY ?? 0));
    const trigger = dy >= THRESHOLD;
    reset();
    if (trigger) refreshData();
  });

  function reset() {
    startY = null;
    pulling = false;
    indicator.classList.remove("visible");
    indicator.style.transform = "";
  }
}

// Clear this event's saved card + setup and reset the UI to defaults.
function resetSaved() {
  clearSaved();
  setNeeded(new Set());
  document.getElementById("target-date").value = toISODate(nextSaturday());
  document.getElementById("use-season").checked = true;
  document.getElementById("use-weather").checked = true;
  document.getElementById("pace-min").value = "";
  document.getElementById("pace-max").value = "";
  updateSeasonMeta();
  markSaved(null);
}

// Default the date picker to the next upcoming Saturday.
function initDate() {
  const input = document.getElementById("target-date");
  input.value = toISODate(nextSaturday());
  updateSeasonMeta();
}

function updateSeasonMeta() {
  const dateVal = document.getElementById("target-date").value;
  const useSeason = document.getElementById("use-season").checked;
  const d = dateVal ? new Date(dateVal + "T00:00:00") : nextSaturday();
  const meta = document.getElementById("season-meta");
  if (!useSeason) {
    meta.textContent = "Seasonal weighting off \u2014 using every event equally.";
    return;
  }
  // Day-of-week sanity note: warn if they picked a non-Saturday.
  const dow = d.getDay();
  const wk = isoWeek(d);
  const note = dow === 6 ? "" : " (note: not a Saturday)";
  meta.textContent = `Week ${wk} of the year${note}.`;
}

function showFatal(msg) {
  const body = document.getElementById("results-body");
  const results = document.getElementById("results");
  body.innerHTML = `<p class="empty">${msg}</p>`;
  results.hidden = false;
}

init();
