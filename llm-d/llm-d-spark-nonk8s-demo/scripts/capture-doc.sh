#!/usr/bin/env bash
# Re-runs every README step from a clean stop and records "prompt + command + real output"
# into logs/capture/NN-*.txt, which are pasted into README.md / README-zh.md as console blocks.
# Not needed to use the demo; kept so the documented output can be regenerated.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=logs/capture; rm -rf "$OUT"; mkdir -p "$OUT"
P='gyliu@spark-3bee:~/llm-d-nonk8s$'
M=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8
blk() { exec >"$OUT/$1.txt" 2>&1; }
run() { echo "$P $*"; bash -c "$*" 2>&1; }

blk 00-host
run 'hostname; uname -m; grep PRETTY /etc/os-release'
run 'nvidia-smi --query-gpu=name,driver_version --format=csv'
run 'docker info --format "runtime={{.DefaultRuntime}} server={{.ServerVersion}}"; nvidia-ctk --version | head -1; docker compose version'
run 'free -g'
run "docker run --rm --gpus all --entrypoint='' nvcr.io/nvidia/vllm:26.08-py3 python3 -c 'import torch,vllm;f,t=torch.cuda.mem_get_info();print(\"vllm\",vllm.__version__,\"| GPU free\",round(f/2**30,1),\"GiB of\",round(t/2**30,1),\"GiB\")'"

blk 01-stop
run 'scripts/down.sh'

blk 02-images
for i in nvcr.io/nvidia/vllm:26.08-py3 ghcr.io/llm-d/llm-d-router-endpoint-picker:main envoyproxy/envoy:v1.36.2 \
         otel/opentelemetry-collector-contrib:0.139.0 jaegertracing/jaeger:2.11.0 prom/prometheus:v3.7.3 grafana/grafana:12.2.1; do
  run "docker pull -q $i"
done
run "docker image inspect ghcr.io/llm-d/llm-d-router-endpoint-picker:main --format '{{.Architecture}} created={{.Created}}'"
run "docker run --rm ghcr.io/llm-d/llm-d-router-endpoint-picker:main --help 2>&1 | grep -E -- '--(config-file|pool-name|secure-serving|health-checking|objectives-file) '"

blk 03-models
run "ls ~/llm-d-cache/huggingface/hub | grep nvidia"
run "du -sh ~/llm-d-cache/huggingface/hub/models--nvidia--*"

blk 04-configs
run 'ls -R configs | head -30'
run 'cat configs/epp/endpoints.yaml'
run 'cat nemotron3-nano-30b.env'
run 'cp nemotron3-nano-30b.env .env && set -a && . ./.env && set +a && envsubst '"'"'${MODEL}'"'"' < configs/epp/config-precise.tmpl.yaml > configs/epp/config-precise.yaml && grep -n -A1 "modelName" configs/epp/config-precise.yaml'
run 'echo EPP_CONFIG=config-precise.yaml >> .env; cat .env'
run "diff <(git -C ~/llm-d show 565373b7:guides/no-kubernetes-deployment/router/envoy/envoy.yaml) configs/envoy/envoy.yaml | head -60"
run 'docker compose --profile obs --profile model --profile router config --services'

blk 05-obs
run 'docker compose --profile obs up -d'
sleep 8
run 'docker ps --format "table {{.Names}}\t{{.Status}}" --filter name=otel --filter name=jaeger --filter name=prometheus --filter name=grafana'
run 'curl -s localhost:9091/-/ready; echo; curl -s localhost:3000/api/health | jq -c .; curl -s -o /dev/null -w "jaeger UI %{http_code}\n" localhost:16686/'
run 'docker logs otel-collector 2>&1 | grep -E "Starting (GRPC|HTTP) server|Everything is ready" | cut -c1-160'

blk 06-vllm0
run 'docker compose --profile model up -d --no-deps vllm-0'
t0=$(date +%s); until curl -sf localhost:8000/v1/models >/dev/null; do sleep 5; done; t1=$(date +%s)
echo "$P until curl -sf localhost:8000/v1/models >/dev/null; do sleep 5; done   # took $((t1-t0))s"
run 'docker logs vllm-0 2>&1 | grep -E "non-default args|Mamba cache mode|Setting attention block size|Model loading took|GPU KV cache size|init engine|Route: /v1/(chat/)?completions/render|Application startup complete" | sed -E "s/^\(APIServer pid=1\) |^\(EngineCore pid=[0-9]+\) //" | cut -c1-260'
run 'curl -s localhost:8000/v1/models | jq -c ".data[] | {id, max_model_len}"'
run 'curl -s localhost:8000/metrics | grep -E "^vllm:cache_config_info" | grep -oE "block_size=\"[0-9]+\"|enable_prefix_caching=\"[A-Za-z]+\"|kv_cache_size_tokens=\"[0-9]+\"" '
run 'ss -ltnp 2>/dev/null | grep -E ":(8000|5556|5559) " | awk "{print \$4}"'

blk 07-vllm1
run 'docker compose --profile model up -d vllm-1'
t0=$(date +%s); until curl -sf localhost:8001/v1/models >/dev/null; do sleep 5; done; t1=$(date +%s)
echo "$P until curl -sf localhost:8001/v1/models >/dev/null; do sleep 5; done   # took $((t1-t0))s"
run 'docker ps --format "table {{.Names}}\t{{.Status}}" --filter name=vllm'
run "docker exec vllm-0 python3 -c 'import torch;f,t=torch.cuda.mem_get_info();print(\"GPU free after 2 replicas:\",round(f/2**30,1),\"GiB\")'"

blk 08-epp
run 'docker compose --profile router up -d --no-deps epp'
sleep 6
run 'docker logs epp 2>&1 | jq -r "select(.body|test(\"GIE build|file-discovery mode|EPP starting|watching endpoints|Connected subscriber|Replay complete|gRPC server listening\")) | [.severity_text, .body, (.endpoint // .port // .path // .\"commit-sha\" // \"\" | tostring)] | @tsv"'
run 'curl -s localhost:9090/metrics | grep -E "^llm_d_epp_kv_cache_events_active_subscribers|^llm_d_epp_pool_ready_pods|^llm_d_epp_inference_pool_ready_pods" ; curl -s localhost:9090/metrics | grep -c "^llm_d_epp"'

blk 09-envoy
run 'docker compose --profile router up -d --no-deps envoy'
sleep 12
run 'curl -s localhost:19000/ready'
run 'curl -s localhost:19000/clusters | grep -E "^ext_proc::.*(health_flags|cx_active)|^otel_collector::.*health_flags"'
run 'docker ps --format "table {{.Names}}\t{{.Status}}"'

blk 10-first-request
run "curl -s localhost:8081/v1/chat/completions -H 'Content-Type: application/json' -d '{\"model\":\"$M\",\"messages\":[{\"role\":\"user\",\"content\":\"In one sentence: what is llm-d?\"}],\"max_tokens\":300}' | jq '{model, content: .choices[0].message.content, reasoning: (.choices[0].message.reasoning // \"\" | .[:160] + \"...\"), usage}'"
run "curl -sN localhost:8081/v1/chat/completions -H 'Content-Type: application/json' -d '{\"model\":\"$M\",\"messages\":[{\"role\":\"user\",\"content\":\"Count from 1 to 3\"}],\"max_tokens\":120,\"stream\":true}' | head -4 | cut -c1-200"
run "curl -s localhost:8081/v1/completions -H 'Content-Type: application/json' -d '{\"model\":\"$M\",\"prompt\":\"The capital of France is\",\"max_tokens\":6,\"temperature\":0}' | jq -c '{text: .choices[0].text, usage}'"
run 'docker logs epp 2>&1 | jq -r "select(.body==\"Request handled\" or (.body|test(\"picked|Picked|selected endpoint\";\"i\"))) | [.body, (.endpoint // .\"x-gateway-destination-endpoint\" // .targetEndpoint // \"\" | tostring)] | @tsv" | tail -3'

blk 11-e2e
run 'python3 scripts/e2e-test.py'

blk 12-trace
run 'python3 scripts/trace-tree.py'

blk 13-bench
run 'python3 scripts/bench.py 1 4 8'

blk 14-hot-reload
run 'grep -c "name: vllm" configs/epp/endpoints.yaml'
run "cp configs/epp/endpoints.yaml /tmp/endpoints.full && python3 -c \"s=open('configs/epp/endpoints.yaml').read();open('configs/epp/endpoints.yaml.tmp','w').write(s.split('  - name: vllm-1')[0])\" && mv configs/epp/endpoints.yaml.tmp configs/epp/endpoints.yaml"
sleep 4
run 'docker logs --since 10s epp 2>&1 | jq -r "select(.logger==null or true) | select(.body|test(\"endpoint|reload\";\"i\")) | [.severity_text,.body,(.name // .endpoint // .count // \"\"|tostring)] | @tsv" | tail -4'
run "for i in 1 2 3 4; do curl -s -o /dev/null -w '%{http_code} ' localhost:8081/v1/chat/completions -H 'Content-Type: application/json' -d '{\"model\":\"$M\",\"messages\":[{\"role\":\"user\",\"content\":\"hi '\$i'\"}],\"max_tokens\":4}'; done; echo"
run 'for p in 8000 8001; do echo -n "vllm :$p request_success_total="; curl -s localhost:$p/metrics | grep "^vllm:request_success_total{" | awk "{s+=\$2} END {print s}"; done'
run 'cp /tmp/endpoints.full configs/epp/endpoints.yaml.tmp && mv configs/epp/endpoints.yaml.tmp configs/epp/endpoints.yaml && grep -c "name: vllm" configs/epp/endpoints.yaml'
touch "$OUT/DONE"
