#!/usr/bin/env python3
"""
Record a new event's start coordinates — run ONCE when you first add an event.

parkrun publishes the course location as structured meta tags on each event's
course page, e.g.:
    <meta name="geo.position" content="51.44417;-0.38025">
    <meta name="geo.placename" content="Crane Park, Twickenham">

This fetches <base>/<slug>/course/ and records those in data/locations.json so
weather works for the event.

Note on the request: parkrun rejects requests whose User-Agent looks like a bot
(a default urllib/curl UA gets a 403), so we send a normal browser User-Agent.
This is a single, one-off request per new venue for one public coordinate — the
weekly results collection still uses your own browser/Shortcut, never this tool.

Deliberately run-once-per-event:
  * Skips any slug already in locations.json (so re-runs are a no-op).
  * One request, with a timeout; fails gracefully with a clear message.

Alternatively, parse a course page you've already saved:
    python3 collector/fetch_location.py --file path/to/saved-course.html

Usage:
    python3 collector/fetch_location.py crane
    python3 collector/fetch_location.py crane --force
    python3 collector/fetch_location.py --file saved.html --slug crane
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCATIONS_FILE = ROOT / "data" / "locations.json"
DEFAULT_BASE = "https://www.parkrun.org.uk"
# A normal browser UA — parkrun 403s obvious bot UAs (default urllib/curl).
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")

_GEO_POS_RE = re.compile(
    r'<meta\s+name=["\']geo\.position["\']\s+content=["\']\s*'
    r'([-\d.]+)\s*;\s*([-\d.]+)\s*["\']', re.IGNORECASE)
_GEO_NAME_RE = re.compile(
    r'<meta\s+name=["\']geo\.placename["\']\s+content=["\']([^"\']*)["\']',
    re.IGNORECASE)
_SLUG_URL_RE = re.compile(r'parkrun\.[a-z.]+/([a-z0-9\-]+)/course', re.IGNORECASE)


def load_locations() -> dict:
    try:
        return json.loads(LOCATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_locations(data: dict) -> None:
    lines = ["{"]
    items = sorted(data.items())
    for i, (slug, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        name = json.dumps(v.get("placename", ""))
        lines.append(
            f'  {json.dumps(slug)}: {{ "lat": {v["lat"]}, "lon": {v["lon"]}, '
            f'"placename": {name} }}{comma}'
        )
    lines.append("}")
    LOCATIONS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_course_html(base: str, slug: str) -> str:
    url = f"{base.rstrip('/')}/{slug}/course/"
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def infer_slug(html: str, fallback: str | None) -> str | None:
    m = _SLUG_URL_RE.search(html)
    if m:
        return m.group(1).lower()
    return fallback


def record(html: str, slug_hint: str | None) -> int:
    m = _GEO_POS_RE.search(html)
    if not m:
        print("No geo.position meta tag found — is this a parkrun course page?",
              file=sys.stderr)
        return 1
    lat, lon = float(m.group(1)), float(m.group(2))
    name_m = _GEO_NAME_RE.search(html)
    placename = name_m.group(1).strip() if name_m else ""
    slug = (infer_slug(html, slug_hint) or "").lower()
    if not slug:
        print("Could not determine the event slug — pass the slug explicitly.",
              file=sys.stderr)
        return 1

    locations = load_locations()
    existed = slug in locations
    locations[slug] = {"lat": lat, "lon": lon, "placename": placename or slug}
    save_locations(locations)
    verb = "Updated" if existed else "Recorded"
    print(f"{verb} '{slug}': {lat}, {lon}  ({placename or 'no placename'})")
    print("Run ./publish.sh (or build.py) to fold weather in for this event.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Record a new event's start coordinates.")
    ap.add_argument("slug", nargs="?", help="parkrun URL slug, e.g. 'crane'")
    ap.add_argument("--file", help="Parse a saved course page instead of fetching.")
    ap.add_argument("--base", default=DEFAULT_BASE, help="parkrun base URL")
    ap.add_argument("--force", action="store_true", help="refetch even if already known")
    args = ap.parse_args()

    if args.file:
        html = Path(args.file).read_text(encoding="utf-8", errors="replace")
        return record(html, args.slug)

    if not args.slug:
        print("Give an event slug (e.g. 'crane') or --file a saved page.", file=sys.stderr)
        return 2
    slug = args.slug.strip().lower()

    if slug in load_locations() and not args.force:
        v = load_locations()[slug]
        print(f"'{slug}' already has coordinates ({v['lat']}, {v['lon']}). "
              f"Use --force to refetch.")
        return 0

    print(f"Fetching course page for '{slug}' (one request)...")
    try:
        html = fetch_course_html(args.base, slug)
    except Exception as e:
        print(f"Could not fetch the course page: {e}", file=sys.stderr)
        print("Add coordinates by hand to data/locations.json instead.", file=sys.stderr)
        return 1
    return record(html, slug)


if __name__ == "__main__":
    raise SystemExit(main())
