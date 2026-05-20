#!/bin/bash
# Notes Viewer launcher — double-click this file in Finder
# Pass --sync as an argument, or set AUTO_SYNC=1, to sync before launching.

cd "$(dirname "$0")"

# Kill any previous instance on our port
lsof -ti tcp:8765 | xargs kill -9 2>/dev/null
sleep 0.3

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Notes Viewer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Optional pre-launch sync
if [[ "${1:-}" == "--sync" ]] || [[ "${AUTO_SYNC:-}" == "1" ]]; then
  echo "  Syncing notes…"
  bash sync.sh || echo "  ⚠  Sync failed — launching with existing notes"
  echo ""
fi

python3 server.py &
SERVER_PID=$!

sleep 1.8
open "http://127.0.0.1:8765"

echo ""
echo "  Close this window to stop the server."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

wait $SERVER_PID
