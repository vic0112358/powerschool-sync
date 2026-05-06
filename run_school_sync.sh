#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

python3 -m py_compile \
  google_calendar_sync.py \
  render_school_report.py \
  run_school_sync.py

python3 ./run_school_sync.py "$@"
