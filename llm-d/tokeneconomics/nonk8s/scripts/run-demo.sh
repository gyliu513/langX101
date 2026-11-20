#!/usr/bin/env bash
# The full demo: baseline (prefix-cache-scorer weight 3) vs incident (weight 0,
# the KubeCon NA 2026 bad config), then build the five datasets and the report.
#   nonk8s/scripts/run-demo.sh [phase-seconds] [concurrency]   (from the tokeneconomics folder)
set -euo pipefail
cd "$(dirname "$0")/../.."           # the tokeneconomics folder (shared Python package)
DUR=${1:-300}
CONC=${2:-12}
OUT=${OUT:-nonk8s/data}
SETTLE=$(awk -F= '/^window_seconds/ {gsub(/ /,"",$2); print $2}' nonk8s/configs/demo.toml)
mkdir -p "$OUT"

nonk8s/scripts/set-prefix-weight.sh 3
python3 -m attribution.driver --phase baseline --note "prefix-cache-scorer weight 3" \
  --duration "$DUR" --concurrency "$CONC" --out "$OUT"

nonk8s/scripts/set-prefix-weight.sh 0
python3 -m attribution.driver --phase incident --note "prefix-cache-scorer weight 0" \
  --duration "$DUR" --concurrency "$CONC" --out "$OUT"

nonk8s/scripts/set-prefix-weight.sh 3          # restore the healthy config
echo "waiting ${SETTLE}s for the last outcomes' settlement window..."
sleep $((SETTLE + 5))
python3 -m attribution.build --data "$OUT" --config nonk8s/configs/demo.toml
python3 -m attribution.report --data "$OUT"
