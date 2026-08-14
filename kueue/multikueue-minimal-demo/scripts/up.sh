#!/usr/bin/env bash
# One-shot: build the whole environment. Run the run-demo-*.sh scripts afterwards.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

"${DEMO_ROOT}/scripts/0-create-clusters.sh"
"${DEMO_ROOT}/scripts/1-install-frameworks.sh"
"${DEMO_ROOT}/scripts/2-install-kueue.sh"
"${DEMO_ROOT}/scripts/3-setup-workers.sh"
"${DEMO_ROOT}/scripts/4-connect.sh"
"${DEMO_ROOT}/scripts/5-setup-manager.sh"

log "environment ready. Now try:"
echo "  ./scripts/run-demo-job.sh      # example 1 — batch/v1 Job"
echo "  ./scripts/run-demo-jobset.sh   # example 2 — JobSet"
echo "  ./scripts/run-demo-rayjob.sh   # example 3 — RayJob"
