#!/usr/bin/env bash
# Records "prompt + command + real output" for every README step into
# logs/capture/NN-*.txt (pasted into README.md / README-zh.md).
# Not needed to use the demo; kept so the documented output can be regenerated.
# Run after scripts/run-demo.sh has produced data/.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=logs/capture; rm -rf "$OUT"; mkdir -p "$OUT"
P='gyliu@spark-3bee:~/tokeneconomics$'
NONK8S_DIR=${NONK8S_DIR:-$HOME/llm-d-nonk8s}
blk() { exec >"$OUT/$1.txt" 2>&1; }
run() { echo "$P $*"; bash -c "$*" 2>&1; }

blk 00-host
run 'hostname; uname -m; grep PRETTY /etc/os-release'
run 'nvidia-smi --query-gpu=name,driver_version --format=csv'
run 'docker compose version; python3 --version'

blk 01-stack
run "docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -E 'vllm|epp|envoy|otel|jaeger|prometheus|grafana' | sort"
run "curl -s localhost:8081/v1/models | python3 -c 'import json,sys; print([m[\"id\"] for m in json.load(sys.stdin)[\"data\"]])'"

blk 02-probe
run "curl -s localhost:8081/v1/chat/completions -H 'Content-Type: application/json' \
  -H 'traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01' \
  -H 'baggage: focus.workload.id=support_bot,focus.task.id=task-probe-1,focus.outcome.id=ticket-probe-1' \
  -d '{\"model\":\"Qwen/Qwen2.5-1.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi\"}],\"max_tokens\":8}' \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r[\"choices\"][0][\"message\"][\"content\"], r[\"usage\"])'"

blk 03-weight
run "NONK8S_DIR=$NONK8S_DIR scripts/set-prefix-weight.sh 0 2>&1 | grep -v -E '^ *Container'"
run "NONK8S_DIR=$NONK8S_DIR scripts/set-prefix-weight.sh 3 2>&1 | grep -v -E '^ *Container'"

blk 04-trace
run "python3 scripts/trace-tree.py \$(python3 - <<'PY'
import json
rows=[json.loads(l) for l in open('data/requests.jsonl')]
r=[x for x in rows if x['phase']=='baseline' and x['step']=='compute' and x['trace_id']][-1]
print(r['trace_id'])
PY
)"

blk 05-datasets
for t in cost_and_usage telemetry task outcome value; do
  run "head -3 data/$t.csv; echo ...; wc -l < data/$t.csv"
done

blk 06-sql
run "sqlite3 -header -column data/tokeneconomics.db \"SELECT phase, WorkloadId, requests, kv_cache_hit_ratio, prefill_gpu_s, decode_gpu_s, printf('%.4f', cost_usd) cost FROM kpi_infra\""
run "sqlite3 -header -column data/tokeneconomics.db \"SELECT phase, WorkloadId, tasks, task_yield, sla_survival, printf('%.5f', cpqo) cpqo, printf('%.3f', gpu_s_per_qo) gpu_s_per_qo, printf('%.2f', estimated) value FROM kpi_workload\""
run "sqlite3 -header -column data/tokeneconomics.db \"SELECT OutcomeEntryNotes, COUNT(*) n FROM outcome GROUP BY 1 ORDER BY 2 DESC\""
