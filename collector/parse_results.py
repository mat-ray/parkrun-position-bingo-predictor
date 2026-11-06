#!/usr/bin/env python3
"""
Parkrun Position Bingo Predictor — results collector / parser.

Reads saved parkrun results pages and extracts each finisher's position + time
(plus gender / age group where available), merging every event into a single raw
dataset. Two input formats are supported:

  * .html  — Safari "Save As -> Page Source" of a results page.
  * .txt   — plain-text dump (e.g. from the iOS Shortcut): a header line with
             "DD/MM/YYYY | #NNN" followed by "<pos> <name> <mm:ss>" entries
             (or "<pos> Unknown" for finishers with no recorded time).

Idempotent: re-running picks up any new files you've added without duplicating
events (dedup is by event number; a .txt and .html for the same event collapse
to one).

Usage:
    python3 collector/parse_results.py                 # parse ./Kingston, write data
    python3 collector/parse_results.py --event-dir Kingston --slug kingston

This step does NO network access. You supply the HTML by browsing normally and
saving the page source yourself.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

@dataclass
class Finisher:
    position: int
    time_seconds: int
    gender: str
    age_group: str


@dataclass
class Event:
    slug: str          # e.g. "kingston"
    event_number: int  # e.g. 788
    date: str          # ISO "YYYY-MM-DD"
    finishers: list[Finisher]
    name: str = ""     # official event name from the page, e.g. "Crane Park"


# Each finisher row in the saved page looks like:
#   <tr class="Results-table-row" ... data-position="1" data-gender="Male"
#       data-agegroup="VM45-49" ...>
#       ...
#       <td class="Results-table-td--time ..."> <div class="compact">17:12</div> ...
_ROW_RE = re.compile(r'<tr class="Results-table-row".*?</tr>', re.S)
_POSITION_RE = re.compile(r'data-position="(\d+)"')
_GENDER_RE = re.compile(r'data-gender="([^"]*)"')
_AGEGROUP_RE = re.compile(r'data-agegroup="([^"]*)"')
_TIME_CELL_RE = re.compile(
    r'Results-table-td--time.*?<div class="compact"[^>]*>\s*([\d:]+)\s*</div>', re.S
)
# Header: <span class="format-date">2026-10-31</span> ... <span>#788</span>
_DATE_RE = re.compile(r'format-date">\s*(\d{4}-\d{2}-\d{2})')
_EVENTNO_RE = re.compile(r'<span>#(\d+)</span>')


def _time_to_seconds(txt: str) -> int | None:
    """'17:12' -> 1032 ; '1:02:03' -> 3723. Returns None if unparseable."""
    parts = txt.strip().split(":")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + int(s)
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + int(s)
    return None


def _normalise_date(raw: str) -> str | None:
    """Return ISO 'YYYY-MM-DD' from either 'YYYY-MM-DD' or 'DD/MM/YYYY'."""
    raw = raw.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return raw
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return None


# Text-dump header, e.g. "... Kingston parkrun 31/10/2026 | #788 547 finishers"
_TXT_HEADER_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*#(\d+)")
# Event name: the words immediately before "parkrun" in the header line, e.g.
# "Kingston parkrun" -> "Kingston", "Littlehampton Prom parkrun" -> "...". We
# never append "parkrun" ourselves.
_NAME_RE = re.compile(r"([A-Z][A-Za-z'&.\- ]*?)\s+parkrun\b")


def _extract_name(text: str) -> str:
    m = _NAME_RE.search(text)
    return m.group(1).strip() if m else ""
# A finisher entry in the text dump: position, then either a time or "Unknown".
# The lookahead keeps names (which contain spaces) from swallowing the next row.
_TXT_ENTRY_RE = re.compile(
    r"(\d+)\s+(?:Unknown|.+?\s+(\d{1,2}:\d{2}(?::\d{2})?))"
    r"(?=\s+\d+\s|\s+\D|\s*$)"
)


def parse_text_event(text: str, slug: str) -> Event | None:
    """Parse a plain-text results dump (iOS Shortcut format)."""
    head = _TXT_HEADER_RE.search(text)
    if not head:
        return None
    date = _normalise_date(head.group(1))
    event_number = int(head.group(2))
    if date is None:
        return None

    # Only scan from the finisher list onward, if the marker is present.
    start = text.find("Finishers")
    body = text[start:] if start != -1 else text

    finishers: list[Finisher] = []
    expected = 1  # positions must climb 1, 2, 3, ...; this rejects footer noise
    for m in _TXT_ENTRY_RE.finditer(body):
        pos = int(m.group(1))
        if pos != expected:
            # Once the strict sequence breaks we've left the results table
            # (the page footer contains stray numbers and timestamps).
            if pos > expected + 1:
                break
            continue
        expected += 1
        time_txt = m.group(2)
        if time_txt is None:
            continue  # "Unknown" — no recorded time
        secs = _time_to_seconds(time_txt)
        if secs is None:
            continue
        finishers.append(
            Finisher(position=pos, time_seconds=secs, gender="", age_group="")
        )

    if not finishers:
        return None
    finishers.sort(key=lambda f: f.position)
    return Event(slug=slug, event_number=event_number, date=date,
                 finishers=finishers, name=_extract_name(text))


def parse_html_event(html: str, slug: str) -> Event | None:
    """Parse one saved HTML results page into an Event, or None if it isn't a
    recognisable single-event results page."""
    date_m = _DATE_RE.search(html)
    evno_m = _EVENTNO_RE.search(html)
    if not date_m or not evno_m:
        return None

    finishers: list[Finisher] = []
    for row in _ROW_RE.findall(html):
        pos_m = _POSITION_RE.search(row)
        time_m = _TIME_CELL_RE.search(row)
        if not pos_m or not time_m:
            continue  # e.g. "unknown" finisher with no recorded time
        secs = _time_to_seconds(time_m.group(1))
        if secs is None:
            continue
        finishers.append(
            Finisher(
                position=int(pos_m.group(1)),
                time_seconds=secs,
                gender=(_GENDER_RE.search(row).group(1) if _GENDER_RE.search(row) else ""),
                age_group=(_AGEGROUP_RE.search(row).group(1) if _AGEGROUP_RE.search(row) else ""),
            )
        )

    if not finishers:
        return None

    finishers.sort(key=lambda f: f.position)
    return Event(
        slug=slug,
        event_number=int(evno_m.group(1)),
        date=_normalise_date(date_m.group(1)),
        finishers=finishers,
        name=_extract_name(html),
    )


class BotCheckPage(Exception):
    """Raised when a saved file is a 'confirm you are human' interstitial rather
    than a results page (the shortcut got rate-limited)."""


class CancelledEvent(Exception):
    """Raised when a saved page is for an event that didn't run (no finishers).
    This is a real-world outcome, not a bad save — re-fetching won't help.

    Two sub-cases, both meaning "no event that week":
      * reason="cancelled" — the page explicitly reads "<date> | CANCELLED".
      * reason="notfound"  — parkrun serves a 404 "page not found" for that
                             week's URL (cancellations aren't always shown as
                             such; a missing week can just 404)."""
    def __init__(self, date: str | None, reason: str = "cancelled"):
        super().__init__(f"{reason} ({date or 'unknown date'})")
        self.date = date
        self.reason = reason


# Phrases that identify an anti-bot / CAPTCHA interstitial instead of results.
_BOTCHECK_MARKERS = (
    "confirm you are human",
    "security check before continuing",
    "verifies that you are not a bot",
)

# A cancelled event's header reads "<date> | CANCELLED" with no event number.
_CANCELLED_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}\s*\|\s*CANCELLED", re.I)

# parkrun serves a "Page not found" 404 for a week with no event. The page
# carries no date (the only date is in the filename), so these two markers
# together — the 404 headline plus the standard apology line — identify it
# without false-matching a real results page.
_NOTFOUND_MARKERS = (
    "page not found",
    "couldn't find the page you were looking for",
)

# Pull an ISO date out of a filename stem like "worthing-2026-10-03" or
# "worthing 03 Oct 2026" — used when the page itself has no date (404s).
_FILENAME_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _looks_like_botcheck(content: str) -> bool:
    low = content.lower()
    return any(marker in low for marker in _BOTCHECK_MARKERS)


def _looks_like_notfound(content: str) -> bool:
    low = content.lower()
    return all(marker in low for marker in _NOTFOUND_MARKERS)


def _date_from_filename(stem: str) -> str | None:
    m = _FILENAME_DATE_RE.search(stem)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_file(path: Path, slug: str) -> Event | None:
    """Dispatch to the right parser based on file extension.

    Raises BotCheckPage for a 'confirm you are human' interstitial, or
    CancelledEvent for a cancelled event / 404 "no event this week" page."""
    content = path.read_text(encoding="utf-8", errors="replace")
    if _looks_like_botcheck(content):
        raise BotCheckPage()
    cancel = _CANCELLED_RE.search(content)
    if cancel:
        date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", content)
        raise CancelledEvent(_normalise_date(date_m.group(1)) if date_m else None,
                             reason="cancelled")
    if _looks_like_notfound(content):
        # A 404 has no in-page date; fall back to the date in the filename.
        raise CancelledEvent(_date_from_filename(path.stem), reason="notfound")
    if path.suffix.lower() == ".txt":
        return parse_text_event(content, slug)
    if path.suffix.lower() in (".html", ".htm"):
        return parse_html_event(content, slug)
    return None


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

# A results file smaller than this is almost certainly a failed/partial save.
_MIN_FILE_BYTES = 200


def _plausibility_warning(ev: Event) -> str | None:
    """Return a human-readable warning if a parsed event looks incomplete, else
    None. Catches truncated saves that parse but only yield a handful of rows,
    or where the finishers don't start near the front of the field."""
    positions = [f.position for f in ev.finishers]
    if len(positions) < 20:
        return f"only {len(positions)} finishers — likely a truncated save"
    first = min(positions)
    if first > 5:
        return f"first finisher is position {first} — top of the field missing"
    # Big gap between how many we have and the field size suggests a partial save.
    field = max(positions)
    coverage = len(positions) / field if field else 0
    if coverage < 0.6:
        return (f"only {len(positions)} of ~{field} positions present "
                f"({coverage:.0%}) — likely partial")
    return None


def collect(event_dir: Path, slug: str) -> tuple[list[Event], list[str], list[str]]:
    """Parse every .html/.txt under event_dir, deduped by event number. When the
    same event appears in more than one file, the one with more finishers wins
    (HTML carries gender/age-group, so it's preferred on a tie).

    Returns (events, problems, cancelled):
      * problems  — files that were empty/unparseable/incomplete (need action)
      * cancelled — weeks with no event: either explicitly CANCELLED pages or
                    parkrun 404 "page not found" pages (informational; no action
                    possible — re-fetching a cancelled/404 week never yields
                    results)
    """
    events: dict[int, Event] = {}
    problems: list[str] = []
    cancelled: list[str] = []
    files = sorted(
        [p for p in event_dir.rglob("*")
         if p.suffix.lower() in (".html", ".htm", ".txt")]
    )
    if not files:
        print(f"  no .html/.txt files found under {event_dir}", file=sys.stderr)
    for path in files:
        try:
            size = path.stat().st_size
        except OSError as e:
            problems.append(f"{path.name}: cannot stat ({e})")
            print(f"  skip {path.name}: {e}", file=sys.stderr)
            continue
        if size < _MIN_FILE_BYTES:
            problems.append(f"{path.name}: empty/tiny ({size} bytes) — re-fetch this one")
            print(f"  skip {path.name}: empty/tiny ({size} bytes)", file=sys.stderr)
            continue
        try:
            ev = parse_file(path, slug)
        except BotCheckPage:
            problems.append(f"{path.name}: bot-check page (rate-limited) — re-fetch this one")
            print(f"  skip {path.name}: bot-check page (rate-limited)", file=sys.stderr)
            continue
        except CancelledEvent as c:
            label = ("event cancelled" if c.reason == "cancelled"
                     else "no event — 404 page")
            cancelled.append(f"{path.name}: {label} ({c.date})")
            print(f"  info {path.name}: {label} ({c.date})", file=sys.stderr)
            continue
        except OSError as e:
            problems.append(f"{path.name}: read error ({e})")
            print(f"  skip {path.name}: {e}", file=sys.stderr)
            continue
        if ev is None:
            problems.append(f"{path.name}: not a recognisable results page")
            print(f"  skip {path.name}: not a recognisable results page", file=sys.stderr)
            continue
        warn = _plausibility_warning(ev)
        if warn is not None:
            problems.append(f"{path.name} (#{ev.event_number}): {warn}")
            print(f"  WARN {path.name}: {warn}", file=sys.stderr)
        existing = events.get(ev.event_number)
        if existing is not None:
            new_has_detail = any(f.gender or f.age_group for f in ev.finishers)
            old_has_detail = any(f.gender or f.age_group for f in existing.finishers)
            # Keep the richer source: more finishers wins; on a tie, the one
            # carrying gender/age-group (HTML) wins.
            better = (
                len(ev.finishers) > len(existing.finishers)
                or (len(ev.finishers) == len(existing.finishers)
                    and new_has_detail and not old_has_detail)
            )
            if not better:
                print(f"  dedup {path.name}: #{ev.event_number} already covered "
                      f"by a richer source")
                continue
        events[ev.event_number] = ev
        print(f"  parsed {path.name}: #{ev.event_number} {ev.date} "
              f"({len(ev.finishers)} finishers)")
    return [events[k] for k in sorted(events)], problems, cancelled


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse saved parkrun results pages.")
    ap.add_argument("--event-dir", default="Kingston",
                    help="Folder containing saved .html results pages.")
    ap.add_argument("--slug", default=None,
                    help="Event slug (defaults to lowercased event-dir name).")
    ap.add_argument("--out", default="data/raw",
                    help="Output folder for raw parsed JSON.")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    event_dir = (root / args.event_dir).resolve()
    slug = args.slug or args.event_dir.lower()
    out_dir = (root / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Collecting '{slug}' from {event_dir}")
    events, problems, cancelled = collect(event_dir, slug)
    if not events:
        print("No events parsed. Nothing written.", file=sys.stderr)
        return 1

    # Event display name, taken from the pages themselves (most common value),
    # falling back to the slug. We never append the word "parkrun".
    from collections import Counter
    names = Counter(e.name for e in events if e.name)
    display_name = names.most_common(1)[0][0] if names else slug

    out_path = out_dir / f"{slug}.json"
    payload = {
        "slug": slug,
        "name": display_name,
        "event_count": len(events),
        "events": [
            {
                "event_number": e.event_number,
                "date": e.date,
                "finishers": [asdict(f) for f in e.finishers],
            }
            for e in events
        ],
    }
    out_path.write_text(json.dumps(payload), encoding="utf-8")
    total = sum(len(e.finishers) for e in events)
    print(f"\nWrote {out_path.relative_to(root)}: "
          f"{len(events)} event(s), {total} finisher rows.")

    # Report gaps in the event-number sequence so missing SAVES are obvious.
    # NB: parkrun numbering stays contiguous across cancellations — a cancelled
    # week does NOT consume an event number — so a gap here means a results page
    # we haven't captured yet, NOT a week the event didn't run.
    numbers = sorted(e.event_number for e in events)
    missing = [n for n in range(numbers[0], numbers[-1] + 1) if n not in set(numbers)]
    print(f"Event range: #{numbers[0]}..#{numbers[-1]}")
    if missing:
        print(f"Missing events in that range ({len(missing)}): "
              + ", ".join(f"#{n}" for n in missing))

    # Report gaps in the DATE sequence — the only reliable signal that a week
    # was cancelled / didn't run, since cancelled events leave no row and no
    # number in parkrun's event history. Consecutive events more than 7 days
    # apart imply at least one skipped Saturday. We tolerate the Christmas/New
    # Year extra events (25/12 and 01/01 can sit only a few days from their
    # neighbours) by only flagging gaps that skip a whole Saturday or more.
    from datetime import date as _date, timedelta as _td

    def _iso(d: str) -> _date:
        y, m, dd = (int(x) for x in d.split("-"))
        return _date(y, m, dd)

    # Classify each date gap using the number-contiguity invariant:
    #   * numbers CONTIGUOUS across the gap  -> inferred cancellation(s). Every
    #     held event in the span is already in the data, so the missing
    #     Saturdays are weeks the event genuinely didn't run.
    #   * numbers NOT contiguous (some #s missing) -> we're simply missing those
    #     saves; the gap is a data hole, not (necessarily) a cancellation. Go
    #     fetch the missing event numbers to resolve it.
    # Number-contiguity has to be checked FIRST: it's the precondition that lets
    # a date gap be read as a cancellation at all.
    have_numbers = set(e.event_number for e in events)
    dated = sorted((_iso(e.date), e.event_number) for e in events)
    cancellation_gaps: list[str] = []
    missingsave_gaps: list[str] = []
    for (d_prev, n_prev), (d_next, n_next) in zip(dated, dated[1:]):
        delta = (d_next - d_prev).days
        if delta <= 7:
            continue  # normal weekly cadence (or a legit mid-week extra event)
        # Saturdays strictly between the two events — candidate no-event weeks.
        skipped = []
        cur = d_prev + _td(days=1)
        while cur < d_next:
            if cur.weekday() == 5:  # Saturday
                skipped.append(cur.isoformat())
            cur += _td(days=1)
        if not skipped:
            continue
        # Any event numbers between the two ends that we DON'T have?
        missing_nums = [n for n in range(n_prev + 1, n_next) if n not in have_numbers]
        span = (f"#{n_prev} ({d_prev.isoformat()}) -> #{n_next} "
                f"({d_next.isoformat()}): {len(skipped)} missing Saturday(s): "
                + ", ".join(skipped))
        if missing_nums:
            missingsave_gaps.append(
                span + "  [numbers missing: "
                + ", ".join(f"#{n}" for n in missing_nums)
                + " — likely uncaptured saves, not cancellations]"
            )
        else:
            cancellation_gaps.append(span + "  [numbers contiguous — inferred cancellation]")

    if cancellation_gaps:
        print(f"\nInferred cancellations ({len(cancellation_gaps)} span(s)) — "
              f"date gaps with contiguous event numbers, so the event genuinely "
              f"didn't run those weeks:")
        for g in cancellation_gaps:
            print(f"  - {g}")
    if missingsave_gaps:
        print(f"\nDate gaps that are MISSING SAVES ({len(missingsave_gaps)} span(s)) "
              f"— event numbers are absent, so fetch those #s to fill them in:")
        for g in missingsave_gaps:
            print(f"  - {g}")

    if cancelled:
        print(f"\n{len(cancelled)} week(s) with no event — cancelled or 404 "
              f"(no results — nothing to fix):")
        for c in cancelled:
            print(f"  - {c}")

    if problems:
        print(f"\n{len(problems)} file(s) need attention:")
        for p in problems:
            print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
