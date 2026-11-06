#!/usr/bin/env bash
# Publish: ingest new downloads, rebuild the data bundle, then commit & push the
# rebuilt app so GitHub Pages redeploys and your installed PWA picks up the new
# data. (The app is hosted at a stable https URL; the phone updates from there,
# not from this laptop.)
#
#   ./publish.sh              # ingest + build + commit + push (default)
#   ./publish.sh --no-push    # ingest + build only (don't commit/push)
#   ./publish.sh --serve      # ingest + build, then serve locally for a preview
#   ./publish.sh --serve30    # serve for 30 minutes (1-360) instead of pushing
#   ./publish.sh --serve 9000 # serve on a different port
#
# Notes:
#   * Default = publish to the web. A push to `app/**` triggers the GitHub Pages
#     deploy workflow; the installed PWA refreshes its data on next launch.
#   * --serve is a LOCAL preview only (handy before pushing, or to view on the
#     Mac). It does NOT update the hosted app. Stop it with Ctrl+C.
#   * Only the build OUTPUTS under app/ are committed, so unrelated edits
#     elsewhere in your working tree are left untouched.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PORT=8777
MODE="push"          # push | none | serve
SERVE_MINUTES=10
BRANCH="main"

# Parse args: --no-push, --serve, --serveMMM (1-360), and/or a bare port number.
for arg in "$@"; do
  case "${arg}" in
    --no-push)
      MODE="none" ;;
    --serve)
      MODE="serve" ;;
    --serve*)
      mins="${arg#--serve}"
      if ! [[ "${mins}" =~ ^[0-9]+$ ]] || [ "${mins}" -lt 1 ] || [ "${mins}" -gt 360 ]; then
        echo "Error: --serveMMM needs an integer 1-360 (got '${mins}')." >&2
        exit 2
      fi
      MODE="serve"; SERVE_MINUTES="${mins}" ;;
    ''|*[!0-9]*)
      echo "Error: unrecognised argument '${arg}'." >&2
      echo "Use --no-push, --serve, --serveMMM (1-360), and/or a port number." >&2
      exit 2 ;;
    *)
      PORT="${arg}" ;;   # bare integer = port
  esac
done

# Step 1: fold any new downloads from latestresults/ into their event folders.
echo "==> Ingesting latestresults/ ..."
if ! python3 "${HERE}/collector/ingest.py"; then
  echo
  printf "Ingest reported problems above. Continue with the build anyway? [y/N] "
  read -r reply
  case "${reply}" in
    [Yy]*) echo "Continuing." ;;
    *) echo "Aborted — fix the files in latestresults/ and re-run."; exit 1 ;;
  esac
fi

# Step 2: rebuild the bundle the app (and GitHub Pages) serve.
echo "==> Rebuilding data bundle..."
python3 "${HERE}/collector/build.py"

# ---------------------------------------------------------------------------
# --serve: local preview only. Does NOT touch git / the hosted app.
# ---------------------------------------------------------------------------
if [ "${MODE}" = "serve" ]; then
  TIMEOUT=$((SERVE_MINUTES * 60))
  if lsof -ti "tcp:${PORT}" >/dev/null 2>&1; then
    echo "==> Port ${PORT} busy; stopping the old listener."
    kill "$(lsof -ti "tcp:${PORT}")" 2>/dev/null || true
    sleep 1
  fi
  IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<your-laptop-ip>')"
  echo
  echo "==> LOCAL PREVIEW for $((TIMEOUT / 60)) min (Ctrl+C to stop):"
  echo "      http://localhost:${PORT}/"
  echo "      http://${IP}:${PORT}/   (same Wi-Fi)"
  echo "    (This does NOT update the hosted app — run without --serve to publish.)"
  echo
  ( cd "${HERE}/app" && exec python3 -m http.server "${PORT}" ) &
  SERVER_PID=$!
  cleanup() { kill "${SERVER_PID}" 2>/dev/null || true; wait "${SERVER_PID}" 2>/dev/null || true; echo; echo "==> Server stopped."; }
  trap cleanup EXIT INT TERM
  SECONDS_LEFT="${TIMEOUT}"
  while kill -0 "${SERVER_PID}" 2>/dev/null && [ "${SECONDS_LEFT}" -gt 0 ]; do
    sleep 1; SECONDS_LEFT=$((SECONDS_LEFT - 1))
  done
  [ "${SECONDS_LEFT}" -le 0 ] && { echo; echo "==> ${SERVE_MINUTES}-minute limit reached — shutting down."; }
  exit 0
fi

# --no-push: rebuild only.
if [ "${MODE}" = "none" ]; then
  echo
  echo "==> Build complete. Not committing/pushing (--no-push)."
  echo "    To publish later: commit app/ and push to '${BRANCH}'."
  exit 0
fi

# ---------------------------------------------------------------------------
# Default: commit the rebuilt app outputs and push, triggering a Pages redeploy.
# ---------------------------------------------------------------------------
cd "${HERE}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: not a git repository — can't push. (Run from the project repo.)" >&2
  exit 1
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Error: no 'origin' remote configured — nothing to push to." >&2
  exit 1
fi

# Stage only the build outputs, so unrelated edits elsewhere aren't committed.
git add app/data.js app/data app/index.standalone.html 2>/dev/null || true

if git diff --cached --quiet; then
  echo
  echo "==> No data changes to publish — the hosted app is already up to date."
  exit 0
fi

STAMP="$(date '+%Y-%m-%d %H:%M')"
echo "==> Committing rebuilt app data (${STAMP})..."
git commit -q -m "data: rebuild app bundle (${STAMP})"

echo "==> Pushing to origin/${BRANCH} (triggers GitHub Pages deploy)..."
git push -q origin "${BRANCH}"

echo
echo "==> Published. GitHub Pages will redeploy in ~1 minute:"
echo "      https://mat-ray.github.io/parkrun-position-bingo-predictor/"
echo "    Open (or relaunch) the installed app to pull the fresh data."
