#!/usr/bin/env python3
"""Print the routing evidence of two traces side by side (before / after).

  compare-traces.py <before> <after> [--jaeger http://localhost:16686]

Each of <before>/<after> is a trace_id (read from Jaeger) or a saved
`/api/traces/<id>` JSON file (the in-memory Jaeger forgets old traces).
"""
import os
import argparse
import json
import urllib.request

FIELDS = [
    ("match_block_keys", "llm_d.kv_cache.prefix_match.longest_chain", "longest_chain"),
    ("match_block_keys", "llm_d.kv_cache.prefix_match.pods_matched", "pods_matched"),
    ("scorer.prefix-cache-scorer", "llm_d.epp.scorer.weight", "prefix scorer weight"),
    ("scorer.prefix-cache-scorer", "llm_d.epp.scorer.score.max", "prefix scorer score.max"),
    ("pick_endpoints", "llm_d.epp.picker.top_scores", "picker top_scores"),
    ("llm_request", "gen_ai.latency.time_in_model_prefill", "vLLM prefill"),
    ("llm_request", "gen_ai.latency.time_to_first_token", "vLLM TTFT"),
]


def attrs(jaeger, tid):
    if os.path.exists(tid):
        t = json.load(open(tid))["data"][0]
    else:
        t = json.load(urllib.request.urlopen(f"{jaeger}/api/traces/{tid}"))["data"][0]
    spans = {s["operationName"]: s for s in t["spans"]}
    out = {}
    for op, key, label in FIELDS:
        v = next((x["value"] for x in spans[op]["tags"] if x["key"] == key), None)
        if label.startswith("vLLM"):
            v = f"{v * 1000:.0f} ms"
        elif label == "picker top_scores":
            v = "[" + ", ".join(f"{float(s):.2f}" for s in json.loads(v)) + "]"
        out[label] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--jaeger", default="http://localhost:16686")
    a = ap.parse_args()
    b, c = attrs(a.jaeger, a.before), attrs(a.jaeger, a.after)
    tb, ta = (json.load(open(x))["data"][0]["traceID"] if os.path.exists(x) else x for x in (a.before, a.after))
    print(f"{'':26}{'prefix w=3.0':>16}{'prefix w=0.0':>16}")
    print(f"{'trace_id':26}{tb[:8]:>16}{ta[:8]:>16}")
    for _, _, label in FIELDS:
        print(f"{label:26}{str(b[label]):>16}{str(c[label]):>16}")


if __name__ == "__main__":
    main()
