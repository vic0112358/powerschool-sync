#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-${SCRIPT_DIR}/.smoke-output/single-table}"
DEPLOY="${DEPLOY_PUBLIC:-0}"

cd "${SCRIPT_DIR}"
mkdir -p "${OUT_DIR}"

python3 -m json.tool school_sync_config.json >/dev/null
python3 -m json.tool test_fixtures/single_table_items.json >/dev/null

python3 -m py_compile render_school_report.py

./render_school_report.py \
  --input test_fixtures/single_table_items.json \
  --private-output "${OUT_DIR}/private_single_table.html" \
  --public-output "${OUT_DIR}/public_single_table.html" \
  --check

if rg -n "gmail|mail\\.google|Source Email|Open source|PayPal|paypal" "${OUT_DIR}/public_single_table.html"; then
  echo "Public privacy check failed." >&2
  exit 1
fi

echo "Single-table smoke preview:"
echo "  private: ${OUT_DIR}/private_single_table.html"
echo "  public:  ${OUT_DIR}/public_single_table.html"

if [[ "${DEPLOY}" == "1" ]]; then
  ./deploy_public_to_gh_pages.sh
fi
