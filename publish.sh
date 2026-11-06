#!/usr/bin/env bash
# Publish: ingest new downloads, rebuild the data bundle, then (optionally)
# serve the app so the installed PWA on your phone can pull the fresh data.
#
#   ./publish.sh              # rebuild + serve on :8777 for 10 minutes (default)
#   ./publish.sh --no-serve   # rebuild only, don't serve (e.g. from a Shortcut)
#   ./publish.sh --serve30    # serve for 30 minutes (1-360)
#   ./publish.sh 9000         # serve on a different port
#   ./publish.sh --serve5 9000  # flags and port can be combined, any order
#
# Stop early any time with Ctrl+C.
#
# Workflow: drop this week's downloads into latestresults/ (or add saved pages
# to an event folder) -> ./publish.sh -> on your phone (same Wi-Fi) open the
# installed app or the printed URL once, so the service worker fetches the new
# data and re-caches it. After that it's good offline again.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PORT=8777
SERVE=1
SERVE_MINUTES=10

# Parse args: --no-serve, --serveMMM (1-360), or a bare port number, any order.
for arg in "$@"; do
  case "${arg}" in
    --no-serve)
      SERVE=0 ;;
    --serve*)
      mins="${arg#--serve}"
      if ! [[ "${mins}" =~ ^[0-9]+$ ]] || [ "${mins}" -lt 1 ] || [ "${mins}" -gt 360 ]; then
        echo "Error: --serveMMM needs an integer 1-360 (got '${mins}')." >&2
        exit 2
      fi
      SERVE=1; SERVE_MINUTES="${mins}" ;;
    ''|*[!0-9]*)
      echo "Error: unrecognised argument '${arg}'." >&2
      echo "Use --no-serve, --serveMMM (1-360), and/or a port number." >&2
      exit 2 ;;
    *)
      PORT="${arg}" ;;   # bare integer = port
  esac
done
TIMEOUT=$((SERVE_MINUTES * 60))

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

echo "==> Rebuilding data bundle..."
python3 "${HERE}/collector/build.py"

# --no-serve: rebuild only (e.g. when triggered headlessly from a Shortcut).
if [ "${SERVE}" = 0 ]; then
  echo
  echo "==> Build complete. Not serving (--no-serve)."
  exit 0
fi

# Free the port if a previous run left something behind.
if lsof -ti "tcp:${PORT}" >/dev/null 2>&1; then
  echo "==> Port ${PORT} busy; stopping the old listener."
  kill "$(lsof -ti "tcp:${PORT}")" 2>/dev/null || true
  sleep 1
fi

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<your-laptop-ip>')"

echo
echo "==> Serving for $((TIMEOUT / 60)) min (Ctrl+C to stop early):"
echo "      http://localhost:${PORT}/"
echo "      http://${IP}:${PORT}/   (open on your phone, same Wi-Fi)"
echo

# Start the server in the background.
( cd "${HERE}/app" && exec python3 -m http.server "${PORT}" ) &
SERVER_PID=$!

# Always clean up the server on exit (Ctrl+C, timeout, or error).
cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
  echo
  echo "==> Server stopped."
}
trap cleanup EXIT INT TERM

# Wait for either the timeout to elapse or the server to die on its own.
SECONDS_LEFT="${TIMEOUT}"
while kill -0 "${SERVER_PID}" 2>/dev/null && [ "${SECONDS_LEFT}" -gt 0 ]; do
  sleep 1
  SECONDS_LEFT=$((SECONDS_LEFT - 1))
done

if [ "${SECONDS_LEFT}" -le 0 ]; then
  echo
  echo "==> ${SERVE_MINUTES}-minute limit reached — shutting down."
fi
