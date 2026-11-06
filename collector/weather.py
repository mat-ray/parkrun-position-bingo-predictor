#!/usr/bin/env python3
"""
Weather collector (Kingston only, for now) — fetches 9am historical weather for
every Kingston event date and joins it to the results, so we can TEST whether
weather predicts field size / shifts the time-position mapping.

This is a research/analysis step. It does NOT touch the live app or its data
bundle. Output goes to data/weather/kingston_weather.json.

Source: Open-Meteo Historical Weather API (free, no key required).
  https://open-meteo.com/en/docs/historical-weather-api

Politeness / terms:
  * One batched request covering the whole date span (not one per event), so we
    make a single API call rather than ~150.
  * Results cached to disk; re-runs reuse the cache and only fetch dates we
    don't already have.
  * A descriptive User-Agent and a small delay between any (rare) extra calls.
Open-Meteo asks non-commercial users to stay under ~10k calls/day; we use ~1.

Usage:
    python3 collector/weather.py
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "weather"
LOCATIONS_FILE = ROOT / "data" / "locations.json"


def load_locations() -> dict[str, tuple[float, float]]:
    """Event start coordinates, slug -> (lat, lon), read from data/locations.json.
    Precise enough for weather (grid-snapped anyway). New events are added with
    collector/fetch_location.py (once per event)."""
    try:
        raw = json.loads(LOCATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for slug, v in raw.items():
        if isinstance(v, dict) and "lat" in v and "lon" in v:
            out[slug] = (v["lat"], v["lon"])
    return out


# Loaded once; `LOCATIONS[slug] -> (lat, lon)`.
LOCATIONS = load_locations()

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "PositionBingoPredictor/1.0 (personal research; weather hypothesis test)"


def load_event_dates(slug: str) -> list[str]:
    data = json.loads((RAW_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    return sorted({e["date"] for e in data["events"]})


def load_cache(slug: str) -> dict[str, dict]:
    cache = OUT_DIR / f"{slug}_weather_cache.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    return {}


def save_cache(slug: str, cache: dict[str, dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{slug}_weather_cache.json").write_text(
        json.dumps(cache, indent=2), encoding="utf-8")


def fetch_range(lat: float, lon: float, start: str, end: str) -> dict[str, dict]:
    """Fetch hourly weather for [start, end] in one call; return a map of
    date -> 9am {temp_c, precip_mm, wind_kmh}."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
        "timezone": "Europe/London",
    }
    url = ARCHIVE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    times = data["hourly"]["time"]
    temp = data["hourly"]["temperature_2m"]
    precip = data["hourly"]["precipitation"]
    wind = data["hourly"]["wind_speed_10m"]

    out: dict[str, dict] = {}
    for i, t in enumerate(times):
        if t.endswith("T09:00"):           # 9am local (parkrun start)
            date = t[:10]
            out[date] = {
                "temp_c": temp[i],
                "precip_mm": precip[i],
                "wind_kmh": wind[i],
            }
    return out


def collect_slug(slug: str) -> int:
    if slug not in LOCATIONS:
        print(f"  no coordinates known for '{slug}' — skipping.")
        return 0
    raw_path = RAW_DIR / f"{slug}.json"
    if not raw_path.exists():
        print(f"  no parsed data for '{slug}' ({raw_path}) — run the parser first.")
        return 0

    lat, lon = LOCATIONS[slug]
    dates = load_event_dates(slug)
    cache = load_cache(slug)
    missing = [d for d in dates if d not in cache]
    print(f"[{slug}] {len(dates)} dates; {len(cache)} cached; {len(missing)} to fetch.")

    if missing:
        start, end = min(missing), max(missing)
        print(f"[{slug}] fetching {start} .. {end} from Open-Meteo (single request)...")
        fetched = fetch_range(lat, lon, start, end)
        time.sleep(1)  # polite pause between events' calls
        for d in missing:
            if d in fetched:
                cache[d] = fetched[d]
            else:
                print(f"  warning: no 9am data for {d}")
        save_cache(slug, cache)

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    joined = []
    for e in raw["events"]:
        w = cache.get(e["date"])
        field = max((f["position"] for f in e["finishers"]), default=0)
        joined.append({
            "event_number": e["event_number"],
            "date": e["date"],
            "field_size": field,
            "weather": w,
        })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{slug}_weather.json"
    out.write_text(json.dumps({"slug": slug, "events": joined}, indent=2),
                   encoding="utf-8")
    have = sum(1 for j in joined if j["weather"])
    print(f"[{slug}] wrote {out.relative_to(ROOT)}: {len(joined)} events, "
          f"{have} with weather.\n")
    return have


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch 9am historical weather per event.")
    ap.add_argument("--slug", default="all",
                    help="Event slug, or 'all' for every known location.")
    args = ap.parse_args()

    slugs = list(LOCATIONS) if args.slug == "all" else [args.slug]
    total = 0
    for slug in slugs:
        total += collect_slug(slug)
    if total == 0:
        print("No weather collected.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
