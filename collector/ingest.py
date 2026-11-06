#!/usr/bin/env python3
"""
Ingest step: route newly-downloaded result files from ./latestresults into the
right event source folder, ready for the normal build to fold them in.

Flow (run automatically at the start of publish.sh):
  1. For each file in latestresults/, determine which event it belongs to —
     authoritatively from the event name inside the file, falling back to the
     filename prefix.
  2. MOVE it into that event's source folder (creating the folder for a brand
     new event, with a clear notice).
  3. Skip files that are empty, bot-check pages, or already present for that
     event+date. Report anything unroutable.

Exit codes:
  0  — all files routed cleanly (or nothing to do)
  1  — one or more files could not be routed / looked problematic
        (publish.sh prompts Y/n before continuing)

No network access.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_results import (
    _extract_name, _looks_like_botcheck, _CANCELLED_RE, _normalise_date,
    _TXT_HEADER_RE, _DATE_RE, _EVENTNO_RE,
)
import fetch_location
from fetch_location import (
    _GEO_POS_RE, _GEO_NAME_RE, infer_slug, load_locations, save_locations,
)

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "latestresults"
RAW_EVENTS = ROOT / "raweventdata"   # one subfolder per event
MIN_BYTES = 200


def existing_event_dirs() -> dict[str, Path]:
    """Map a normalised event key -> existing folder under raweventdata/."""
    out = {}
    if RAW_EVENTS.exists():
        for p in sorted(RAW_EVENTS.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                out[_key(p.name)] = p
    return out


def _key(s: str) -> str:
    """Normalise a slug/folder for matching: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _slug_from_filename(stem: str) -> str:
    """Extract the parkrun URL slug (filename prefix before the first date).
    Handles 'crane-2026-10-31', 'crane 31 Oct 2026', 'crane_2026-10-31'."""
    # Everything up to the first separator-then-digit or separator-then-month.
    m = re.match(r"(.+?)[ \-_]+(?:\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                 stem, re.IGNORECASE)
    slug = m.group(1) if m else stem
    return slug.strip().lower()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _event_date(content: str) -> str | None:
    """Pull the event date (ISO) from either text or HTML content."""
    m = _TXT_HEADER_RE.search(content)
    if m:
        return _normalise_date(m.group(1))
    m = _DATE_RE.search(content)
    if m:
        return _normalise_date(m.group(1))
    return None


def _handle_course_page(path: Path, content: str) -> tuple[str, str]:
    """A dropped course page: record the event's coordinates and remove the
    file. Returns a ('coords', detail) action."""
    m = _GEO_POS_RE.search(content)
    lat, lon = float(m.group(1)), float(m.group(2))
    name_m = _GEO_NAME_RE.search(content)
    placename = name_m.group(1).strip() if name_m else ""
    # Prefer the slug from the page's canonical URL; fall back to the filename.
    fname_slug = re.split(r"[-_ ]?course|[-_ .]", path.stem, maxsplit=1)[0].lower()
    slug = (infer_slug(content, fname_slug) or "").lower()
    if not slug:
        return "problem", f"{path.name}: course page but couldn't determine slug"

    locations = load_locations()
    existed = slug in locations
    locations[slug] = {"lat": lat, "lon": lon, "placename": placename or slug}
    save_locations(locations)
    path.unlink(missing_ok=True)   # consume it; coords now live in locations.json
    verb = "updated" if existed else "recorded"
    return "coords", f"{slug}: {verb} coords {lat},{lon} ({placename or 'no name'})"


def route_file(path: Path, dirs: dict[str, Path]) -> tuple[str, str]:
    """Decide where a file goes. Returns (action, detail).
    action in {"move", "newdir", "skip", "problem", "coords"}."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return "problem", f"cannot stat ({e})"
    if size < MIN_BYTES:
        return "problem", f"empty/tiny ({size} bytes)"

    content = _read(path)
    if _looks_like_botcheck(content):
        return "problem", "bot-check page (rate-limited)"

    # Course page? (has the geo.position meta tag). Record the event's coords in
    # data/locations.json and consume the file — these are dropped once per new
    # venue, not weekly.
    if _GEO_POS_RE.search(content):
        return _handle_course_page(path, content)

    # Route by the parkrun URL SLUG, which is the filename prefix (everything
    # before the first date token) — e.g. "crane-2026-10-31.txt" -> "crane".
    # Folder names are the same slugs, so this matches directly. The in-file
    # display name ("Crane Park") is used only for a friendly notice, never for
    # routing (it wouldn't match the slug folder).
    slug = _slug_from_filename(path.stem)
    if not slug:
        return "problem", "could not determine event slug from filename"
    display = _extract_name(content) or slug

    key = _key(slug)
    target = dirs.get(key)
    is_new = target is None
    if target is None:
        # Brand-new event: folder named with the slug, under raweventdata/.
        target = RAW_EVENTS / slug
        action = "newdir"
    else:
        action = "move"

    # Duplicate guard: skip if a file for this event+date is already there.
    cancelled = bool(_CANCELLED_RE.search(content))
    date = _event_date(content)
    if date and not cancelled and target.exists():
        for existing in target.glob("*"):
            if existing.suffix.lower() in (".txt", ".html", ".htm"):
                try:
                    if _event_date(_read(existing)) == date:
                        return "skip", f"{slug}: {date} already present"
                except OSError:
                    pass

    # Perform the move.
    target.mkdir(parents=True, exist_ok=True)
    dest = target / path.name
    # Avoid clobbering a different file with the same name.
    if dest.exists():
        return "skip", f"{dest.relative_to(ROOT)} already exists"
    path.rename(dest)
    dirs[key] = target  # so subsequent files in this run route to it too
    label = f"{slug} ({display})" if display and _key(display) != key else slug
    detail = f"{label} <- {path.name}"
    return ("newdir" if is_new else "move"), detail


def main() -> int:
    if not INBOX.exists():
        print(f"(no {INBOX.name}/ folder — nothing to ingest)")
        return 0
    files = sorted(p for p in INBOX.iterdir()
                   if p.is_file() and p.suffix.lower() in (".txt", ".html", ".htm"))
    if not files:
        print(f"(latestresults/ is empty — nothing to ingest)")
        return 0

    print(f"Ingesting {len(files)} file(s) from latestresults/ ...")
    dirs = existing_event_dirs()
    moved = skipped = coords = 0
    problems = []
    new_events = []
    for f in files:
        action, detail = route_file(f, dirs)
        if action == "move":
            moved += 1
            print(f"  moved: {detail}")
        elif action == "newdir":
            moved += 1
            # The slug is the first token of the label (slugs have no spaces).
            new_events.append(detail.split(" <- ")[0].split()[0])
            print(f"  NEW EVENT: {detail}")
        elif action == "coords":
            coords += 1
            print(f"  coords: {detail}")
        elif action == "skip":
            skipped += 1
            # A skip means the data is already in the dataset, so this file is a
            # redundant re-download — remove it so latestresults/ stays clean.
            # (Problem files below are deliberately kept for you to act on.)
            f.unlink(missing_ok=True)
            print(f"  skip:  {detail} (removed duplicate)")
        else:
            problems.append(f"{f.name}: {detail}")
            print(f"  PROBLEM: {f.name}: {detail}", file=sys.stderr)

    print(f"\nIngest: {moved} moved, {coords} coords, {skipped} skipped, "
          f"{len(problems)} problem(s).")
    if new_events:
        uniq = sorted(set(new_events))
        print("New event folder(s) created: " + ", ".join(uniq))
        # Auto-fetch coordinates for each genuinely new event (one request each,
        # once ever). Only for events that don't already have coords, and a
        # failure is non-fatal — it just leaves the usual reminder.
        locations = load_locations()
        for slug in uniq:
            if slug in locations:
                continue
            print(f"  fetching coordinates for new event '{slug}'...")
            try:
                html = fetch_location.fetch_course_html(fetch_location.DEFAULT_BASE, slug)
                rc = fetch_location.record(html, slug)
                if rc != 0:
                    print(f"  (couldn't read coords for '{slug}' — add manually "
                          f"with: python3 collector/fetch_location.py {slug})")
            except Exception as e:
                print(f"  (coord fetch failed for '{slug}': {e}; add manually "
                      f"with: python3 collector/fetch_location.py {slug})")
    if problems:
        print("\nProblems (left in latestresults/ for you to check):")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
