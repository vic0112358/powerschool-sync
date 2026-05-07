#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${SCRIPT_DIR}/.pycache-prefix}"
mkdir -p "${PYTHONPYCACHEPREFIX}"

"${PYTHON_BIN}" -m py_compile \
  google_calendar_sync.py \
  render_school_report.py \
  run_school_sync.py

"${PYTHON_BIN}" ./run_school_sync.py "$@"
