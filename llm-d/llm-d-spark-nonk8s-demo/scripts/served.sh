for p in 8000 8001; do printf "vllm :%s served=%s\n" $p $(curl -s localhost:$p/metrics | awk '/^vllm:request_success_total\{/ {s+=$2} END {print s}'); done
