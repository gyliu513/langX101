#!/usr/bin/env bash
# End-to-end check for llm-d-router PR #2774 (issue #2637): Prometheus exemplars
# on llm_d_epp_request_duration_seconds. Needs scripts/port-forward.sh running.
set -uo pipefail
GW=http://localhost:8080; EPP=http://localhost:9090; PROM=http://localhost:9091; JAEGER=http://localhost:16686
OM_ACCEPT='application/openmetrics-text;version=1.0.0,text/plain;version=0.0.4;q=0.5'
pass() { echo "  ✅ $*"; }; fail() { echo "  ❌ $*"; RC=1; }; RC=0

echo "1) send 3 requests through the gateway"
for i in 1 2 3; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 60 $GW/v1/chat/completions -H 'Content-Type: application/json' \
    -d "{\"model\":\"Qwen/Qwen2.5-0.5B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"exemplar check $i\"}],\"max_tokens\":$((10*i))}")
  [ "$code" = 200 ] && pass "request $i -> HTTP 200" || fail "request $i -> HTTP $code"
done

echo "2) EPP /metrics: OpenMetrics negotiation + exemplar on the wire"
AUTH=()
if [ "$(curl -s -o /dev/null -w '%{http_code}' $EPP/metrics)" = 401 ]; then
  TOKEN=$(kubectl get secret -n llm-d inference-gateway-sa-metrics-reader-secret -o jsonpath='{.data.token}' | base64 -d)
  AUTH=(-H "Authorization: Bearer $TOKEN"); echo "  (metrics-endpoint-auth is on: using the chart's SA token)"
fi
om=$(curl -s "${AUTH[@]}" -H "Accept: $OM_ACCEPT" -D /tmp/om.hdr $EPP/metrics)
grep -qi 'content-type: application/openmetrics-text' /tmp/om.hdr && pass "Accept openmetrics -> Content-Type: $(grep -i content-type /tmp/om.hdr | tr -d '\r' | cut -d' ' -f2-)" || fail "no OpenMetrics content-type"
line=$(echo "$om" | grep '^llm_d_epp_request_duration_seconds_bucket' | grep -m1 '# {')
[ -n "$line" ] && pass "exemplar on the wire: $(echo "$line" | sed 's/.*# {/# {/')" || fail "no exemplar in OpenMetrics output"
classic=$(curl -s "${AUTH[@]}" -H 'Accept: text/plain;version=0.0.4' -D /tmp/cl.hdr $EPP/metrics)
grep -qi 'content-type: text/plain' /tmp/cl.hdr && ! echo "$classic" | grep -q '# {' && pass "classic Accept -> text/plain, no exemplars (unchanged for old scrapers)" || fail "classic format changed"

echo "3) exemplar trace_id/span_id resolve in Jaeger"
tid=$(echo "$line" | sed -n 's/.*trace_id="\([0-9a-f]*\)".*/\1/p'); sid=$(echo "$line" | sed -n 's/.*span_id="\([0-9a-f]*\)".*/\1/p')
op=$(curl -s $JAEGER/api/traces/$tid | jq -r --arg s "$sid" '.data[0].spans[] | select(.spanID==$s) | "\(.operationName) \(.duration/1000)ms"')
[ -n "$op" ] && pass "trace $tid / span $sid = EPP span '$op'" || fail "trace/span not found in Jaeger"

echo "4) Prometheus stored the exemplars (exemplar-storage feature)"
n=$(curl -s "$PROM/api/v1/query_exemplars?query=llm_d_epp_request_duration_seconds_bucket&start=$(($(date +%s)-3600))&end=$(date +%s)" | jq '[.data[].exemplars[]] | length')
[ "${n:-0}" -gt 0 ] && pass "$n exemplars in Prometheus (/api/v1/query_exemplars)" || fail "no exemplars in Prometheus"

echo "5) Grafana Prometheus datasource links trace_id -> Jaeger"
curl -s -u admin:admin http://localhost:3000/api/datasources/uid/prometheus | jq -e '.jsonData.exemplarTraceIdDestinations[]|select(.name=="trace_id")' >/dev/null \
  && pass "exemplarTraceIdDestinations configured (open http://localhost:3000/explore, query the histogram with Exemplars: true)" || fail "Grafana datasource has no exemplar destination"
exit $RC
