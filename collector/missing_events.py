#!/usr/bin/env python3
"""
List event numbers we still need to retrieve, per event, straight from the saved
files under raweventdata/ — no build required, no network.

Output (stdout) is ONLY data, one line per event that has gaps, ready to parse
(e.g. from an iOS Shortcut):

    slug;NUM1;NUM2;NUM3
    otherslug;NUM1

Nothing is printed for events with no gaps; if nothing is missing anywhere,
stdout is empty. Human-readable notes go to stderr (use --quiet to silence).

How "missing" is decided
  * Event numbers are contiguous across cancellations (a cancelled week uses no
    number), so any hole in the numbers we hold is a page we haven't captured —
    never a cancellation. Cancelled / 404 / bot-check pages carry no number and
    are ignored.
  * The range checked runs from the lowest to the highest number known for that
    event. "Known" includes files that FAILED (empty, unparseable) but are named
    like <slug>-<number>.txt, so a failed fetch of the newest event is still
    reported even though nothing above it was saved.
  * We can't know the latest event number without the network, so numbers newer
    than anything saved can't be detected unless a failed file names them.

Usage:
    python3 collector/missing_events.py
    python3 collector/missing_events.py --root raweventdata --quiet
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_results import parse_file, BotCheckPage, CancelledEvent  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULT_SUFFIXES = (".html", ".htm", ".txt")

# "<slug>-435", "<slug> 435", "<slug>_435": a number-named file. The slug part
# must equal the folder name, which stops date-named files such as
# "worthing-2026-10-31" or "Crane 14 Dec 2024" being mistaken for event numbers.
#
# The optional trailing "txt"/"html" tolerates the Shortcut's occasional naming
# quirk of "<slug>- 460txt.txt" (a doubled extension with no dot).
_NUMBERED_RE = re.compile(r"^(.+?)[ \-_]+(\d{1,6})(?:txt|html?)?$", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _number_from_filename(stem: str, folder: str) -> int | None:
    m = _NUMBERED_RE.match(stem)
    if m and _norm(m.group(1)) == _norm(folder):
        return int(m.group(2))
    return None


def scan_event_dir(event_dir: Path) -> tuple[set[int], set[int]]:
    """Return (present, failed): event numbers we hold good data for, and event
    numbers named by files that exist but didn't yield a result."""
    present: set[int] = set()
    failed: set[int] = set()
    for path in sorted(p for p in event_dir.rglob("*")
                       if p.is_file() and p.suffix.lower() in RESULT_SUFFIXES):
        ev = None
        try:
            ev = parse_file(path, event_dir.name.lower())
        except (BotCheckPage, OSError):
            pass            # a bad save — treat as failed below
        except CancelledEvent:
            continue        # no event that week: carries no number, not a gap
        if ev is not None:
            present.add(ev.event_number)
        else:
            n = _number_from_filename(path.stem, event_dir.name)
            if n is not None:
                failed.add(n)
    return present, failed


def missing_for(present: set[int], failed: set[int]) -> list[int]:
    known = present | failed
    if not known:
        return []
    return [n for n in range(min(known), max(known) + 1) if n not in present]


def main() -> int:
    ap = argparse.ArgumentParser(description="List missing event numbers per event.")
    ap.add_argument("--root", default=str(ROOT / "raweventdata"),
                    help="Folder containing one subfolder per event.")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress the stderr summary.")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: {root} is not a folder", file=sys.stderr)
        return 2

    lines = []
    for d in sorted(p for p in root.iterdir()
                    if p.is_dir() and not p.name.startswith(".")):
        present, failed = scan_event_dir(d)
        missing = missing_for(present, failed)
        if not args.quiet:
            rng = (f"#{min(present | failed)}..#{max(present | failed)}"
                   if (present | failed) else "no events")
            print(f"{d.name}: {len(present)} held, {len(missing)} missing ({rng})",
                  file=sys.stderr)
        if missing:
            lines.append(d.name.lower() + ";" + ";".join(str(n) for n in missing))

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
