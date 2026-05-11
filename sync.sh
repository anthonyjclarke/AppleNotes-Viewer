#!/bin/bash
# sync.sh — Export notes from Apple Notes using apple-notes-exporter
# https://github.com/kzaremski/apple-notes-exporter
#
# On first run: full export. Subsequent runs: only changed notes (--incremental).
# Requires 'notes-export' binary in PATH, or set NOTES_EXPORT_BIN=/path/to/binary.
# Requires Full Disk Access in System Settings > Privacy & Security.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="${NOTES_EXPORT_BIN:-notes-export}"
CONFIG="$SCRIPT_DIR/config.json"

# Verify the binary is available
if ! command -v "$BINARY" &>/dev/null; then
  echo "ERROR: '$BINARY' not found in PATH." >&2
  echo "  Download from https://github.com/kzaremski/apple-notes-exporter/releases" >&2
  echo "  Place in /usr/local/bin/ or set: export NOTES_EXPORT_BIN=/path/to/notes-export" >&2
  exit 1
fi

# Read the Notes folder path from config.json
if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: config.json not found at $SCRIPT_DIR" >&2
  echo "  Open the app and configure the Notes folder path first." >&2
  exit 1
fi

NOTES_ROOT=$(python3 -c "import json,sys; d=json.load(open('$CONFIG')); print(d.get('notes_root',''))")
if [[ -z "$NOTES_ROOT" ]]; then
  echo "ERROR: notes_root not set in config.json" >&2
  exit 1
fi

echo "Exporting notes to: $NOTES_ROOT"

"$BINARY" export \
  --format html \
  --incremental \
  --output "$NOTES_ROOT"

echo "Done."
