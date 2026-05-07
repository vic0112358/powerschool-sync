#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
LOG_PATH="${PROJECT_DIR}/public_publish.log"
LOCK_DIR="${PROJECT_DIR}/.public-publish-lock"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  python3 -m venv "${PROJECT_DIR}/.venv"
fi

PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
export PATH="${PROJECT_DIR}/.venv/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPYCACHEPREFIX="${PROJECT_DIR}/.pycache-prefix"
mkdir -p "${PYTHONPYCACHEPREFIX}"

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  printf '%s publish skipped: lock exists at %s\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S%z')" "${LOCK_DIR}" >> "${LOG_PATH}"
  exit 0
fi

cleanup() {
  rmdir "${LOCK_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

cd "${PROJECT_DIR}"

{
  printf '\n[%s] public publish start\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"

  "${PYTHON_BIN}" - <<'PY'
import socket
hosts = [
    "oauth2.googleapis.com",
    "accounts.google.com",
    "github.com",
]
for host in hosts:
    socket.getaddrinfo(host, 443)
    print(f"dns_ok {host}")
PY

  # This renders both reports locally, syncs calendars from the existing
  # config/token files, and publishes only the sanitized public site through
  # the gh-pages deploy worktree. It does not stage or commit the private HTML
  # in the main repository worktree.
  ./run_school_sync.sh --trigger cron-safe-public-publish --deploy-gh-pages "$@"

  printf '[%s] public publish done\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
} >> "${LOG_PATH}" 2>&1
