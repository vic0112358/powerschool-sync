#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

python3 -m json.tool school_sync_config.json >/dev/null
python3 -m json.tool test_fixtures/calendar_sync_items.json >/dev/null
python3 -m py_compile google_calendar_sync.py

if [[ ! -f .google-calendar-client.json ]]; then
  echo "Missing .google-calendar-client.json" >&2
  echo "Create a Google OAuth desktop client and place it at ${SCRIPT_DIR}/.google-calendar-client.json" >&2
  exit 2
fi

if [[ ! -f .google-calendar-token.json ]]; then
  echo "OAuth token not initialized. Run:" >&2
  echo "  ./google_calendar_sync.py authorize" >&2
  exit 3
fi

./google_calendar_sync.py sync --input test_fixtures/calendar_sync_items.json --dry-run
