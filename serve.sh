#!/usr/bin/env bash
# Serve the web-app locally. The app uses fetch(), so it must be served over
# http (opening index.html directly with file:// will not work).
#
#   ./serve.sh            # serve on http://localhost:8777
#   ./serve.sh 9000       # serve on a different port
#
# To use it on your phone: run this on your laptop, make sure the phone is on
# the same Wi-Fi, then browse to http://<your-laptop-ip>:8777/
set -euo pipefail
PORT="${1:-8777}"
cd "$(dirname "$0")/app"
IP=$(ipconfig getifaddr en0 2>/dev/null || echo "<your-laptop-ip>")
echo "Serving on:"
echo "  http://localhost:${PORT}/"
echo "  http://${IP}:${PORT}/   (open this on your phone, same Wi-Fi)"
echo
exec python3 -m http.server "${PORT}"
