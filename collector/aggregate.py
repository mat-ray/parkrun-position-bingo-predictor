#!/usr/bin/env python3
"""
Aggregate raw parsed events into a compact lookup the web-app consumes.

Input:  data/raw/<slug>.json      (from parse_results.py)
Output: app/data/<slug>.json      (compact; loaded by the static web-app)

Model
-----
Finish *position* for a given *time* depends on the size/speed of the field,
which varies seasonally. So we don't just average everything together; we bucket
each event by ISO week-of-year and, within each bucket, record the time observed
at each finishing position across all events in that bucket.

For the predictor we invert this: given a target position P we look at the set of
times recorded at position P (optionally restricted to the weeks around a target
date) and report a sensible aim-for range (the inter-quartile-ish band) plus the
median.

With a single event the "distribution" at each position is just that one value;
the structure is identical so it scales seamlessly as more events are added.

No network access.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path


def iso_week(iso_date: str) -> int:
    y, m, d = (int(x) for x in iso_date.split("-"))
    return date(y, m, d).isocalendar().week  # 1..53


def _wk_dist(a: int, b: int) -> int:
    """Circular distance between two ISO weeks on a ~52-week year."""
    r = abs(a - b)
    return min(r, 53 - r)


def quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile over a pre-sorted list."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    pos = (n - 1) * q
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def position_stats(times: list[int]) -> dict:
    """Summary stats + a readable volatility rating for the times recorded at a
    single finishing position across all events."""
    s = sorted(times)
    n = len(s)
    p25 = quantile(s, 0.25)
    p50 = quantile(s, 0.50)
    p75 = quantile(s, 0.75)
    iqr = p75 - p25
    spread = s[-1] - s[0]  # full min-max spread in seconds

    # Volatility: how much the time at this position swings week to week.
    # Based on the inter-quartile range relative to the median. Needs >=3
    # samples to be meaningful; below that we flag it as not-yet-known.
    if n < 2:
        rating = "single"          # one event only — no spread yet
    elif n < 3:
        rating = "low-data"        # two events — indicative only
    else:
        cv = (iqr / p50) if p50 else 0.0
        if cv < 0.04:
            rating = "low"
        elif cv < 0.09:
            rating = "medium"
        else:
            rating = "high"

    return {
        "n": n,
        "min": s[0],
        "max": s[-1],
        "p25": round(p25),
        "p50": round(p50),
        "p75": round(p75),
        "iqr": round(iqr),
        "spread": spread,
        "volatility": rating,
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = (sum((a - mx) ** 2 for a in xs)) ** 0.5
    dy = (sum((b - my) ** 2 for b in ys)) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def _slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of ys on xs (change in field per unit of x)."""
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((a - mx) ** 2 for a in xs)
    if denom == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / denom


def build_weather(slug: str, events: list[dict], root: Path) -> dict | None:
    """Attach per-event 9am weather and pre-compute this event's own, self-
    calibrating weather->field relationship. Returns None if no weather cache
    exists (so the app simply runs without weather for that event)."""
    cache_path = root / "data" / "weather" / f"{slug}_weather_cache.json"
    if not cache_path.exists():
        return None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    WINDY_KMH = 20.0   # "very windy" threshold inferred from the data
    MIN_COND_DAYS = 8  # need at least this many wet/windy days to trust a slope
    SLOPE_FIT_FRAC = 0.7  # only fit over positions up to 70% of a typical field

    # Index events: 9am weather + time-at-each-position, keyed by ISO week.
    by_week_precip: dict[int, list[float]] = defaultdict(list)
    by_week_wind: dict[int, list[float]] = defaultdict(list)
    recs = []  # one per event with weather
    fields = []
    for ev in events:
        w = cache.get(ev["date"])
        if not w:
            continue
        wk = iso_week(ev["date"])
        field = max((f["position"] for f in ev["finishers"]), default=0)
        fields.append(field)
        by_week_precip[wk].append(w["precip_mm"])
        by_week_wind[wk].append(w["wind_kmh"])
        recs.append({
            "wk": wk,
            "wet": w["precip_mm"] > 0,
            "windy": w["wind_kmh"] >= WINDY_KMH,
            "times": {f["position"]: f["time_seconds"] for f in ev["finishers"]},
        })

    if len(recs) < 20:
        return None  # too little to say anything useful

    mean_field = sum(fields) / len(fields)

    # Seasonal weather norms per ISO week (what's "normal" for this time of year).
    week_norm = {}
    for wk in set(list(by_week_precip) + list(by_week_wind)):
        p = by_week_precip.get(wk, [])
        w = by_week_wind.get(wk, [])
        week_norm[str(wk)] = {
            "precip_mm": round(sum(p) / len(p), 2) if p else 0.0,
            "wind_kmh": round(sum(w) / len(w), 1) if w else 0.0,
            "n": max(len(p), len(w)),
        }

    # --- Per-position time-penalty SLOPE (the core of the model) -----------
    # Bad weather thins the field from the BACK: fast regulars show up regardless,
    # casual/slower runners stay home. So the time penalty at a position grows
    # ~linearly with position. We fit, per condition, a slope in seconds-per-
    # place through the origin (intercept is ~0), de-seasonalised.
    cap = max(30, int(SLOPE_FIT_FRAC * mean_field))
    fit_positions = list(range(10, cap, 10))

    def condition_slope(flag: str, min_days: int) -> tuple[float, int]:
        """Fit delta = slope * pos for events where recs[flag] is True, vs the
        seasonal norm. Returns (slope_seconds_per_place, n_condition_days)."""
        cond_days = sum(1 for r in recs if r[flag])
        if cond_days < min_days:
            return 0.0, cond_days
        xs, ys = [], []
        for pos in fit_positions:
            cond, base = [], []
            for r in recs:
                t = r["times"].get(pos)
                if t is None:
                    continue
                peers = [o["times"][pos] for o in recs
                         if o is not r and pos in o["times"]
                         and _wk_dist(o["wk"], r["wk"]) <= 3]
                if len(peers) < 5:
                    continue
                dev = t - (sum(peers) / len(peers))
                (cond if r[flag] else base).append(dev)
            if cond and base:
                xs.append(pos)
                ys.append((sum(cond) / len(cond)) - (sum(base) / len(base)))
        if len(xs) < 3:
            return 0.0, cond_days
        slope = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
        # Only trust a POSITIVE slope (people slow the field); a negative slope
        # is noise/no-effect, so treat it as zero.
        return (round(slope, 4) if slope > 0 else 0.0), cond_days

    wet_slope, wet_days = condition_slope("wet", MIN_COND_DAYS)
    windy_slope, windy_days = condition_slope("windy", MIN_COND_DAYS)

    return {
        "mean_field": round(mean_field),
        "windy_threshold_kmh": WINDY_KMH,
        "fit_cap_pos": cap,
        "sensitivity": {
            # Seconds added to the finish time PER FINISHING PLACE, under each
            # condition (0 if not enough data or no real effect). Applied as
            # slope * target_position.
            "wet_slope": wet_slope,
            "wet_days": wet_days,
            "windy_slope": windy_slope,
            "windy_days": windy_days,
            "n": len(recs),
        },
        "week_norm": week_norm,
    }


def build_odds_curve(events: list[dict]) -> dict:
    """Estimate, by Monte-Carlo over the real event history, the weekly chance of
    ticking at least one needed bingo number when aiming at the best target,
    for a range of 'numbers still needed' (k). Baked into the data so the app
    can show honest odds without shipping the raw per-finisher samples.

    Method: for a random card of k numbers, aim at the median time of the
    shallowest needed position, replay it against a real past event (where did
    that time actually place?), and see if the landed position ticks a needed
    cell. This captures genuine week-to-week scatter."""
    import random
    from collections import defaultdict
    usable = [e for e in events if len(e["finishers"]) > 50]
    if len(usable) < 10:
        return {}

    tbp = defaultdict(list)
    for e in usable:
        for f in e["finishers"]:
            tbp[f["position"]].append(f["time_seconds"])
    import statistics
    med = {p: statistics.median(ts) for p, ts in tbp.items() if len(ts) >= 10}
    pool = sorted(med)
    curves = [sorted((f["time_seconds"], f["position"]) for f in e["finishers"])
              for e in usable]

    def landed(curve, T):
        return min(curve, key=lambda x: abs(x[0] - T))[1]

    rng = random.Random(42)  # fixed seed => reproducible builds

    def p_for_k(k, trials=3000):
        hits = 0
        for _ in range(trials):
            need = set(rng.sample(range(100), k))
            tgt = next((p for p in pool if p % 100 in need), None)
            if tgt is None:
                continue
            c = rng.choice(curves)
            if landed(c, med[tgt]) % 100 in need:
                hits += 1
        return round(hits / trials, 3)

    # One value per k from 1..99 (k=100 is the trivial "guaranteed" case).
    return {str(k): p_for_k(k) for k in range(1, 100)}


def _monotonic_positions(positions: dict) -> None:
    """Mutate `positions` so every stored time is non-decreasing as the finishing
    position increases (isotonic projection via cumulative max).

    Applied independently to each quantile so their ordering within a position
    is preserved. Covers the all-time `stats` (min/p25/p50/p75/max; iqr/spread
    are recomputed to stay consistent) and every ISO-week `seasonal` band
    [n, p25, p50, p75], each week smoothed over its own ascending position
    series. Volatility ratings and sample counts are left untouched — we're
    re-ordering times across positions, not reshaping a position's distribution.
    """
    pos_nums = sorted(int(p) for p in positions)

    # All-time stats: one running max per key, sweeping low->high position.
    running = {}
    for p in pos_nums:
        st = positions[str(p)].get("stats")
        if not st:
            continue
        for key in ("min", "p25", "p50", "p75", "max"):
            if key not in st:
                continue
            prev = running.get(key)
            if prev is not None and st[key] < prev:
                st[key] = prev
            running[key] = st[key]
        # A raised lower quantile could now exceed a higher one within this
        # position; restore the within-position ordering min<=p25<=p50<=p75<=max
        # (and carry any bump forward so the running maxima stay consistent).
        order = ("min", "p25", "p50", "p75", "max")
        for a, b in zip(order, order[1:]):
            if a in st and b in st and st[b] < st[a]:
                st[b] = st[a]
                running[b] = st[b]
        # Keep derived fields coherent with the (possibly raised) quantiles.
        if "p25" in st and "p75" in st:
            st["iqr"] = st["p75"] - st["p25"]
        if "min" in st and "max" in st:
            st["spread"] = st["max"] - st["min"]

    # Seasonal bands: smooth each ISO week over its own ascending positions.
    # Gather the set of weeks present anywhere, then for each week sweep the
    # positions that have an entry for it.
    weeks = set()
    for p in pos_nums:
        weeks.update(positions[str(p)].get("seasonal", {}).keys())
    for wk in weeks:
        run_p25 = run_p50 = run_p75 = None
        for p in pos_nums:
            band = positions[str(p)].get("seasonal", {}).get(wk)
            if band is None:
                continue
            # band == [n, p25, p50, p75]
            if run_p25 is not None and band[1] < run_p25:
                band[1] = run_p25
            run_p25 = band[1]
            if run_p50 is not None and band[2] < run_p50:
                band[2] = run_p50
            run_p50 = band[2]
            if run_p75 is not None and band[3] < run_p75:
                band[3] = run_p75
            run_p75 = band[3]
            # A raised p25 could now exceed p50/p75 within this position; keep
            # the within-position ordering p25 <= p50 <= p75.
            if band[2] < band[1]:
                band[2] = band[1]
                run_p50 = band[2]
            if band[3] < band[2]:
                band[3] = band[2]
                run_p75 = band[3]


def aggregate(raw: dict, root: Path | None = None) -> dict:
    slug = raw["slug"]
    events = raw["events"]

    # position -> list of (time_seconds, iso_week, event_date)
    by_position: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    # iso_week -> list of field sizes (max position seen that week)
    field_by_week: dict[int, list[int]] = defaultdict(list)

    for ev in events:
        wk = iso_week(ev["date"])
        fs = ev["finishers"]
        if fs:
            field_by_week[wk].append(max(f["position"] for f in fs))
        for f in fs:
            by_position[f["position"]].append((f["time_seconds"], wk, ev["date"]))

    # For each position we emit:
    #   stats    — all-time band + volatility (the default prediction)
    #   seasonal — per-ISO-week pre-computed band over the +/-3-week window, so
    #              the app's "weight by time of year" works WITHOUT shipping the
    #              bulky raw per-finisher samples. The raw samples remain in
    #              data/raw for auditing / exact recomputation if ever needed.
    # Seasonal bands are stored compactly as arrays [n, p25, p50, p75] keyed by
    # ISO week — the all-time `stats` object already carries min/max/volatility,
    # and the app derives the seasonal IQR and a volatility label from these.
    # (Compact arrays keep the bundle ~5x smaller than verbose objects.)
    SEASON_WINDOW = 3

    def _q(sorted_vals, qq):
        return round(quantile(sorted_vals, qq))

    positions = {}
    for pos, recs in by_position.items():
        times_all = [t for (t, _w, _d) in recs]
        by_wk: dict[int, list[int]] = defaultdict(list)
        for (t, w, _d) in recs:
            by_wk[w].append(t)
        seasonal = {}
        for target_wk in sorted(by_wk):
            window = []
            for w, ts in by_wk.items():
                if min(abs(w - target_wk), 53 - abs(w - target_wk)) <= SEASON_WINDOW:
                    window.extend(ts)
            if window:
                s = sorted(window)
                seasonal[str(target_wk)] = [len(s), _q(s, 0.25), _q(s, 0.50), _q(s, 0.75)]
        positions[str(pos)] = {
            "stats": position_stats(times_all),
            "seasonal": seasonal,
        }

    # --- Enforce monotonicity across position --------------------------------
    # Physically, finish time cannot DECREASE as the finishing position grows
    # (someone further back was beaten by more runners), so the time->position
    # curve is non-decreasing. But each position's band is estimated
    # independently from a small, noisy sample, so adjacent positions can invert
    # by a few seconds purely by chance (e.g. 113th reading a hair faster than
    # 111th). That's confusing in the UI and makes the opportunity/odds maths
    # (which read these medians) slightly incoherent.
    #
    # We fix it with an isotonic projection: a left-to-right cumulative maximum
    # over increasing position, applied independently to each quantile. This
    # only ever RAISES a value to meet the one before it (never lowers), which
    # is the correct direction — it removes "faster to finish further back"
    # artifacts while keeping every number a real observed quantile elsewhere on
    # the curve. Applied to the all-time band (p25/p50/p75 + min/max) and to
    # each ISO-week seasonal band, each week smoothed over its own position
    # series so a sparse week can't distort a dense one.
    _monotonic_positions(positions)

    field_size = {
        str(wk): {
            "min": min(sizes),
            "max": max(sizes),
            "avg": round(sum(sizes) / len(sizes)),
            "n": len(sizes),
        }
        for wk, sizes in field_by_week.items()
    }

    all_fields = [s for sizes in field_by_week.values() for s in sizes]
    max_pos = max((int(p) for p in positions), default=0)

    result = {
        "slug": slug,
        "name": raw.get("name", slug),
        "event_count": len(events),
        "date_range": [events[0]["date"], events[-1]["date"]] if events else [],
        "max_position": max_pos,
        "field_overall": {
            "min": min(all_fields) if all_fields else 0,
            "max": max(all_fields) if all_fields else 0,
            "avg": round(sum(all_fields) / len(all_fields)) if all_fields else 0,
        },
        "field_by_week": field_size,
        # k (numbers still needed) -> estimated weekly tick-probability when
        # aiming at the best target, from a simulation over the real history.
        "odds_by_k": build_odds_curve(events),
        # position -> { stats: all-time band, seasonal: {iso-week: windowed band} }
        "positions": positions,
    }

    # Optional, self-calibrating weather block (absent if no weather cached).
    if root is not None:
        weather = build_weather(slug, events, root)
        if weather is not None:
            result["weather"] = weather

    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="kingston")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="app/data")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    raw_path = (root / args.raw / f"{args.slug}.json").resolve()
    out_dir = (root / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    agg = aggregate(raw, root=root)
    out_path = out_dir / f"{args.slug}.json"
    out_path.write_text(json.dumps(agg), encoding="utf-8")

    print(f"Aggregated {agg['event_count']} event(s) -> {out_path.relative_to(root)}")
    print(f"  positions covered: 1..{agg['max_position']}")
    print(f"  field size (min/avg/max): {agg['field_overall']['min']}/"
          f"{agg['field_overall']['avg']}/{agg['field_overall']['max']}")
    if "weather" in agg:
        s = agg["weather"]["sensitivity"]
        print(f"  weather: wet slope {s['wet_slope']:+.3f} s/place "
              f"({s['wet_days']} wet days), "
              f"windy slope {s['windy_slope']:+.3f} s/place "
              f"({s['windy_days']} windy days)  [n={s['n']}]")
    else:
        print("  weather: none (no cache) — runs without weather adjustment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
