#!/usr/bin/env python3
"""
One-shot build: parse every event folder, aggregate, and write the app manifest.

Convention: each top-level folder that contains saved .html results pages is one
event. Folder name -> slug (lowercased). Run this whenever you add new saved
pages or a new event folder.

    python3 collector/build.py

No network access.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from weather import LOCATIONS as WEATHER_LOCATIONS  # event coords for forecasts

ROOT = Path(__file__).resolve().parent.parent
COLLECTOR = ROOT / "collector"
APP_DATA = ROOT / "app" / "data"
RAW_EVENTS = ROOT / "raweventdata"   # one subfolder per event


def _has_results_files(p: Path) -> bool:
    return any(
        f.suffix.lower() in (".html", ".htm", ".txt")
        for f in p.rglob("*") if f.is_file()
    )


def find_event_dirs() -> list[Path]:
    """Event folders live under raweventdata/ (one per event)."""
    if not RAW_EVENTS.exists():
        return []
    dirs = []
    for p in sorted(RAW_EVENTS.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if _has_results_files(p):
            dirs.append(p)
    return dirs


def run(args: list[str]) -> None:
    print("$", " ".join(args))
    r = subprocess.run([sys.executable, *args], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args)}")


def run_soft(args: list[str], note: str) -> None:
    """Run a step that may need the network. On failure, warn and carry on —
    the build must not depend on internet access. Weather is cached, so a miss
    just means the aggregator uses whatever weather is already on disk."""
    print("$", " ".join(args))
    try:
        r = subprocess.run([sys.executable, *args], cwd=ROOT, timeout=120)
        if r.returncode != 0:
            print(f"  (soft) {note}: step returned {r.returncode}; continuing.")
    except Exception as e:  # network down, timeout, etc.
        print(f"  (soft) {note}: {e}; continuing with cached data.")


def main() -> int:
    event_dirs = find_event_dirs()
    if not event_dirs:
        print("No event folders with .html files found.", file=sys.stderr)
        return 1

    manifest_events = []
    for d in event_dirs:
        slug = d.name.lower()
        # Pass the path relative to ROOT (parse_results resolves against ROOT).
        rel = str(d.relative_to(ROOT))
        run([str(COLLECTOR / "parse_results.py"), "--event-dir", rel, "--slug", slug])
        # Weather is optional + cached: refresh any new dates, but never let a
        # network hiccup fail the build. Runs before aggregate so the cache is
        # current when aggregate folds weather into the bundle.
        run_soft([str(COLLECTOR / "weather.py"), "--slug", slug],
                 note=f"weather for {slug}")
        run([str(COLLECTOR / "aggregate.py"), "--slug", slug])

        agg = json.loads((APP_DATA / f"{slug}.json").read_text(encoding="utf-8"))
        entry = {
            "slug": slug,
            # Display name comes from the results pages (consistent official
            # capitalisation), not the folder name. Never includes "parkrun".
            "name": agg.get("name", d.name),
            "event_count": agg["event_count"],
            "date_range": agg["date_range"],
            "max_position": agg["max_position"],
        }
        # Coordinates let the app fetch this event's forecast (for the weather
        # adjustment). Only present for events we have a location for.
        if slug in WEATHER_LOCATIONS:
            lat, lon = WEATHER_LOCATIONS[slug]
            entry["lat"] = lat
            entry["lon"] = lon
        manifest_events.append(entry)

    manifest = {"events": manifest_events}
    (APP_DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nWrote app/data/manifest.json with {len(manifest_events)} event(s).")

    # Remind about any events lacking weather coordinates, so the forecast
    # adjustment isn't silently missing for a newly added event.
    no_coords = [e["slug"] for e in manifest_events if "lat" not in e]
    if no_coords:
        print("\nNote: no weather coordinates for: " + ", ".join(no_coords))
        print("  These events work fully, but have NO forecast adjustment until you")
        print("  add their start lat/lon to LOCATIONS in collector/weather.py.")

    # Bundle everything into a single JS file so the app can run from a plain
    # file:// (double-click index.html) with no server. The app prefers this
    # bundle and falls back to fetch() when it isn't present (i.e. served).
    bundle = {
        "manifest": manifest,
        "events": {
            ev["slug"]: json.loads((APP_DATA / f"{ev['slug']}.json").read_text(encoding="utf-8"))
            for ev in manifest_events
        },
    }
    bundle_path = ROOT / "app" / "data.js"
    bundle_path.write_text(
        "// Generated by collector/build.py — do not edit by hand.\n"
        "window.PBP_DATA = " + json.dumps(bundle, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    size_kb = bundle_path.stat().st_size / 1024
    print(f"Wrote app/data.js bundle ({size_kb:.0f} KB) "
          f"— open app/index.html directly, no server needed.")

    write_standalone()

    # Machine-readable list of MISSING event numbers (saves we don't have yet),
    # for feeding into a retrieval shortcut. Printed last so it's easy to grab
    # from the tail of the output. Event numbers are contiguous across
    # cancellations, so every gap in the number sequence is a results page we
    # haven't captured — never a cancelled week. Format, one row per event:
    #     slug;NUM1;NUM2;NUM3
    # Only events that actually have gaps are listed.
    report_missing_event_numbers([e["slug"] for e in manifest_events])
    return 0


def report_missing_event_numbers(slugs: list[str]) -> None:
    """Print, per event, the event numbers missing from data/raw/<slug>.json —
    i.e. saves still to retrieve (gaps are never cancellations). Emits a clearly
    delimited block of `slug;NUM;NUM;...` lines for scripting."""
    lines = []
    for slug in slugs:
        raw_path = ROOT / "data" / "raw" / f"{slug}.json"
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        numbers = sorted(e["event_number"] for e in raw.get("events", []))
        if len(numbers) < 2:
            continue
        have = set(numbers)
        missing = [n for n in range(numbers[0], numbers[-1] + 1) if n not in have]
        if missing:
            lines.append(slug + ";" + ";".join(str(n) for n in missing))

    print("\n=== MISSING EVENT NUMBERS (saves to retrieve; slug;NUM;NUM;...) ===")
    if lines:
        for line in lines:
            print(line)
    else:
        print("(none — every event number in range is present)")
    print("=== END MISSING EVENT NUMBERS ===")


def write_standalone() -> None:
    """Produce a single self-contained app/index.standalone.html with the CSS,
    JS and data bundle all inlined. Handy for iOS Shortcuts (Get Contents of
    File -> Show Web Page), AirDrop, email, or anywhere a single file is easier
    than a folder. The regular index.html (separate files) is unaffected."""
    app_dir = ROOT / "app"
    html = (app_dir / "index.html").read_text(encoding="utf-8")
    css = (app_dir / "style.css").read_text(encoding="utf-8")
    data_js = (app_dir / "data.js").read_text(encoding="utf-8")
    app_js = (app_dir / "app.js").read_text(encoding="utf-8")

    # Inline the stylesheet: replace the <link rel="stylesheet" href="style.css">
    link_re = re.compile(r'<link[^>]*rel=["\']stylesheet["\'][^>]*href=["\']style\.css["\'][^>]*>')
    if link_re.search(html):
        html = link_re.sub(lambda _m: f"<style>\n{css}\n</style>", html, count=1)
    else:
        # Fallback: inject before </head>
        html = html.replace("</head>", f"<style>\n{css}\n</style>\n</head>", 1)

    # Inline the data bundle and app script, in order, replacing their tags.
    # </script> inside the data would break parsing, but JSON never contains it;
    # guard anyway by escaping any literal </script> just in case.
    def esc(js: str) -> str:
        return js.replace("</script>", "<\\/script>")

    # Use replacement *functions* so backslash sequences in the JS (e.g. \u00b7)
    # are inserted verbatim rather than interpreted as regex-template escapes.
    html = re.sub(r'<script[^>]*src=["\']data\.js["\'][^>]*>\s*</script>',
                  lambda _m: f"<script>\n{esc(data_js)}\n</script>", html, count=1)
    html = re.sub(r'<script[^>]*src=["\']app\.js["\'][^>]*>\s*</script>',
                  lambda _m: f"<script>\n{esc(app_js)}\n</script>", html, count=1)

    out = app_dir / "index.standalone.html"
    out.write_text(html, encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"Wrote app/index.standalone.html ({size_kb:.0f} KB) "
          f"— one self-contained file for iOS Shortcuts / AirDrop.")


if __name__ == "__main__":
    raise SystemExit(main())
