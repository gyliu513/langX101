#!/usr/bin/env bash
# Re-records "prompt + command + real output" for the Kubernetes README into
# k8s/logs/capture/NN-*.txt. Run on the Kind host after k8s/scripts/run-demo.sh.
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=k8s/logs/capture; rm -rf "$OUT"; mkdir -p "$OUT"
P='gyliu@spark-3bee:~/tokeneconomics$'
blk() { exec >"$OUT/$1.txt" 2>&1; }
run() { echo "$P $*"; bash -c "$*" 2>&1; }

blk 00-cluster
run 'kubectl config current-context; kubectl get nodes -o wide | cut -c1-120'
run "kubectl get node llm-d-control-plane -o jsonpath='{.status.allocatable.nvidia\.com/gpu}{\" nvidia.com/gpu (GB10 time-sliced x4)\n\"}'"
run "helm list -A | awk '{print \$1, \$2, \$9, \$10}' | column -t"
run "kubectl -n llm-d get pods -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[*].ready,GPU:.spec.containers[*].resources.limits.nvidia\\\\.com/gpu | grep -v te-driver"
run "kubectl -n llm-d get deploy llm-d-epp -o jsonpath='{.spec.template.spec.containers[0].image}{\"\n\"}'"
run "kubectl -n llm-d get deploy precise-prefix-vllm -o jsonpath='{.spec.template.spec.containers[0].image}{\"\n\"}{.spec.template.spec.containers[0].args}{\"\n\"}' | tr ',' '\n' | grep -E 'nvcr|serve|Qwen|prompt-tokens|otlp|kv-cache-memory'"

blk 01-opencost
run 'kubectl -n opencost get pods'
run "curl -s 'http://127.0.0.1:9003/allocation/compute?window=3m&aggregate=namespace,pod&step=1m&resolution=1m&includeIdle=true&accumulate=false' | python3 -c 'import json,sys
for st in json.load(sys.stdin)[\"data\"][:1]:
  for k,a in sorted(st.items()):
    if \"vllm\" in k or \"idle\" in k or \"epp\" in k:
      print(f\"{k:58s} {a[\"window\"][\"start\"]} gpuHours={a.get(\"gpuHours\",0):.4f} gpu=\${a.get(\"gpuCost\",0):.5f} cpu=\${a[\"cpuCost\"]:.5f} total=\${a[\"totalCost\"]:.5f}\")'"

blk 02-probe
run "kubectl -n llm-d run probe --rm -i --restart=Never --image=curlimages/curl:8.11.1 --quiet -- \
  curl -s http://llm-d-inference-gateway.llm-d.svc.cluster.local/v1/chat/completions -H 'Content-Type: application/json' \
  -H 'traceparent: 00-1af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01' \
  -H 'baggage: focus.workload.id=support_bot,focus.task.id=task-probe-1,focus.outcome.id=ticket-probe-1' \
  -d '{\"model\":\"Qwen/Qwen2.5-1.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi\"}],\"max_tokens\":8}' | cut -c1-160"
sleep 8
run "curl -s http://127.0.0.1:16686/api/traces/1af7651916cd43dd8448eb211c80319c | python3 -c 'import json,sys
d=json.load(sys.stdin)[\"data\"][0]; p={k:v[\"serviceName\"] for k,v in d[\"processes\"].items()}
print(len(d[\"spans\"]), \"spans:\", sorted(set(p.values())))
print(\"spans with focus.*/baggage attributes:\", [(p[s[\"processID\"]],s[\"operationName\"],t[\"key\"]) for s in d[\"spans\"] for t in s[\"tags\"] if \"focus\" in t[\"key\"] or \"baggage\" in t[\"key\"]])'"

blk 03-weight
run 'k8s/scripts/set-prefix-weight.sh 0'
run 'k8s/scripts/set-prefix-weight.sh 3'

blk 04-traces
run "python3 scripts/trace-tree.py \$(python3 -c 'import json; r=[json.loads(l) for l in open(\"k8s/data/requests.jsonl\")]; print([x for x in r if x[\"phase\"]==\"baseline\" and x[\"step\"]==\"compute\" and x[\"trace_id\"]][-1][\"trace_id\"])')"
run "python3 scripts/trace-tree.py \$(python3 -c 'import json; r=[json.loads(l) for l in open(\"k8s/data/requests.jsonl\")]; print([x for x in r if x[\"phase\"]==\"incident\" and x[\"step\"]==\"compute\" and x[\"trace_id\"] and x[\"cached_tokens\"]<100][-1][\"trace_id\"])')"

blk 05-datasets
for t in cost_and_usage telemetry task outcome value; do run "head -3 k8s/data/$t.csv | cut -c1-400; echo ...; wc -l < k8s/data/$t.csv"; done

blk 06-sql
DB=k8s/data/tokeneconomics.db
run "sqlite3 -header -column $DB \"SELECT CASE WHEN ResourceId LIKE 'precise-prefix-vllm-%' THEN 'vLLM pods' WHEN ResourceId='__idle__' THEN '__idle__' ELSE 'other llm-d pods' END AS scope, COUNT(*) rows_, printf('%.4f',SUM(EffectiveCost)) cost, printf('%.4f',SUM(x_GpuCost)) gpu, printf('%.4f',SUM(x_CpuCost)) cpu, printf('%.4f',SUM(x_RamCost)) ram FROM cost_and_usage GROUP BY 1\""
run "sqlite3 -header -column $DB \"SELECT phase, WorkloadId, requests, kv_cache_hit_ratio, prefill_gpu_s, decode_gpu_s, printf('%.4f', cost_usd) cost FROM kpi_infra\""
run "sqlite3 -header -column $DB \"SELECT phase, WorkloadId, tasks, task_yield, sla_survival, printf('%.5f', cpqo) cpqo, printf('%.3f', gpu_s_per_qo) gpu_s_per_qo, printf('%.2f', estimated) value FROM kpi_workload\""
run "sqlite3 -header -column $DB \"SELECT phase, printf('%.4f',total_cost) total, printf('%.4f',idle_cost) idle, printf('%.4f',overhead_cost) overhead, printf('%.4f',unlinked_cost) unlinked, scrap_rate FROM kpi_phase\""
run "sqlite3 -header -column $DB \"WITH x AS (SELECT x_Phase, TaskId, COUNT(DISTINCT x_ServingReplica) n FROM telemetry WHERE WorkloadId='support_bot' GROUP BY 1,2) SELECT x_Phase phase, COUNT(*) tasks, SUM(n>1) split_across_pods, ROUND(100.0*SUM(n>1)/COUNT(*),1) pct FROM x GROUP BY 1\""
