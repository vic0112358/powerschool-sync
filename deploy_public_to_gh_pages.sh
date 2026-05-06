#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
CONFIG_PATH="${PROJECT_DIR}/school_sync_config.json"
RUN_LOG_PATH="${PROJECT_DIR}/school_sync_runs.log"
CHECK_ONLY=0
DEPLOY_LOGGED=0

if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
fi

log_deploy_result() {
  local status="$1"
  local deploy_state="$2"
  local note="$3"
  if [[ "${CHECK_ONLY}" == "1" || "${GH_PAGES_SUPPRESS_RUN_LOG:-0}" == "1" ]]; then
    return
  fi
  local lookback_days="unknown"
  if [[ -f "${CONFIG_PATH}" ]]; then
    lookback_days="$(python3 -c 'import json; print(json.load(open("school_sync_config.json")).get("gmail_days_back", "unknown"))' 2>/dev/null || printf 'unknown')"
  fi
  printf '%s | status=%s | trigger=manual-gh-pages-deploy | lookback_days=%s | private_page_changed=no | calendar_added=0 | public_deploy=%s | note=%s\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
    "${status}" \
    "${lookback_days}" \
    "${deploy_state}" \
    "${note}" >> "${RUN_LOG_PATH}"
  DEPLOY_LOGGED=1
}

finish() {
  local code=$?
  if [[ "${code}" != "0" && "${DEPLOY_LOGGED}" == "0" ]]; then
    log_deploy_result "partial" "failed" "GitHub Pages deploy failed before completion"
  fi
}
trap finish EXIT

if [[ "${SCRIPT_DIR}" != "${PROJECT_DIR}" ]]; then
  echo "This deploy script must run from ${PROJECT_DIR}." >&2
  exit 1
fi

cd "${PROJECT_DIR}"

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Missing config file: ${CONFIG_PATH}" >&2
  exit 1
fi

PROVIDER="$(python3 -c 'import json; print(json.load(open("school_sync_config.json"))["public_deploy"]["provider"])')"
BRANCH="$(python3 -c 'import json; print(json.load(open("school_sync_config.json"))["public_deploy"].get("branch", "gh-pages"))')"
SOURCE_DIR="$(python3 -c 'import json; print(json.load(open("school_sync_config.json"))["public_deploy"]["source_dir"])')"
SITE_URL="$(python3 -c 'import json; print(json.load(open("school_sync_config.json"))["public_deploy"].get("site_url", ""))')"

if [[ "${PROVIDER}" != "github_pages" ]]; then
  echo "Configured public_deploy.provider is ${PROVIDER}, not github_pages." >&2
  exit 1
fi

if [[ "${SOURCE_DIR}" != "${PROJECT_DIR}/public_site" ]]; then
  echo "Refusing to deploy unexpected source directory: ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Missing source directory: ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/index.html" ]]; then
  echo "Missing public index: ${SOURCE_DIR}/index.html" >&2
  exit 1
fi

python3 - <<'PY'
from pathlib import Path
from render_school_report import validate_public_privacy
validate_public_privacy(Path("public_site/index.html"))
PY

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Project directory is not a git repository." >&2
  exit 1
fi

ORIGIN_URL="$(git remote get-url origin)"
if [[ "${ORIGIN_URL}" != git@github-personal:vic0112358/powerschool-sync.git ]]; then
  echo "Refusing to deploy with unexpected origin: ${ORIGIN_URL}" >&2
  exit 1
fi

export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-vic0112358}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-vic0112358@users.noreply.github.com}"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-vic0112358}"
export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-vic0112358@users.noreply.github.com}"

if [[ "${CHECK_ONLY}" == "1" ]]; then
  echo "GitHub Pages deploy preflight passed."
  echo "  source: ${SOURCE_DIR}"
  echo "  branch: ${BRANCH}"
  echo "  origin: ${ORIGIN_URL}"
  echo "  site:   ${SITE_URL}"
  exit 0
fi

DEPLOY_DIR="${PROJECT_DIR}/.gh-pages-deploy"
mkdir -p "${DEPLOY_DIR}"

if [[ ! -d "${DEPLOY_DIR}/.git" ]]; then
  git -C "${DEPLOY_DIR}" init
  git -C "${DEPLOY_DIR}" remote add origin "${ORIGIN_URL}"
else
  git -C "${DEPLOY_DIR}" remote set-url origin "${ORIGIN_URL}"
fi

git -C "${DEPLOY_DIR}" fetch origin "${BRANCH}" >/dev/null 2>&1 || true
if git -C "${DEPLOY_DIR}" show-ref --verify --quiet "refs/remotes/origin/${BRANCH}"; then
  git -C "${DEPLOY_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
else
  if git -C "${DEPLOY_DIR}" rev-parse --verify HEAD >/dev/null 2>&1; then
    git -C "${DEPLOY_DIR}" checkout --orphan "${BRANCH}"
  else
    git -C "${DEPLOY_DIR}" checkout --orphan "${BRANCH}" >/dev/null 2>&1 || true
  fi
fi

find "${DEPLOY_DIR}" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "${SOURCE_DIR}/." "${DEPLOY_DIR}/"

touch "${DEPLOY_DIR}/.nojekyll"

git -C "${DEPLOY_DIR}" add -A
if git -C "${DEPLOY_DIR}" diff --cached --quiet; then
  STATE="unchanged"
  echo "GitHub Pages content unchanged; nothing to push."
else
  COMMIT_MESSAGE="Publish school report $(date '+%Y-%m-%d %H:%M:%S %z')"
  git -C "${DEPLOY_DIR}" commit -m "${COMMIT_MESSAGE}"
  git -C "${DEPLOY_DIR}" push origin "${BRANCH}"
  STATE="succeeded"
  echo "Published GitHub Pages branch ${BRANCH}: ${SITE_URL}"
fi

if [[ "${GH_PAGES_SUPPRESS_RUN_LOG:-0}" != "1" ]]; then
  log_deploy_result "success" "${STATE}" "published sanitized public report to GitHub Pages branch ${BRANCH}"
fi
