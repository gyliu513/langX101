#!/usr/bin/env bash
# Switch the current kubectl context between the demo clusters.
#
#   ./scripts/ctx.sh              # list contexts and show the current one
#   ./scripts/ctx.sh manager      # switch to kind-mk-manager
#   ./scripts/ctx.sh worker1      # switch to kind-mk-worker1
#   ./scripts/ctx.sh worker2      # switch to kind-mk-worker2
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

target="${1:-}"

if [[ -z "${target}" ]]; then
  log "demo contexts (* = current):"
  kubectl config get-contexts -o name | grep -E "kind-(${MANAGER}|${WORKERS[0]}|${WORKERS[1]})$" | while read -r c; do
    if [[ "${c}" == "$(kubectl config current-context 2>/dev/null)" ]]; then
      echo "  * ${c}"
    else
      echo "    ${c}"
    fi
  done
  echo
  echo "usage: $0 <manager|worker1|worker2>"
  exit 0
fi

case "${target}" in
  manager|mgr|m)  cluster="${MANAGER}" ;;
  worker1|w1|1)   cluster="${WORKERS[0]}" ;;
  worker2|w2|2)   cluster="${WORKERS[1]}" ;;
  *)              warn "unknown target '${target}' (expected manager|worker1|worker2)"; exit 1 ;;
esac

kubectl config use-context "$(ctx "${cluster}")"
log "now pointing at ${cluster}"
kubectl get nodes
