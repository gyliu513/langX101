"""Cost and Usage rows from OpenCost (the Kubernetes variant of the demo).

OpenCost's allocation API already splits the node bill per pod per step from
Prometheus usage data and the configured prices. We turn each (pod, step) into
one FOCUS-shaped row, so the Consumption Scope is the pod:

  * a vLLM pod's row is split over the requests it served (ActivityWeight);
  * another pod of the inference namespace (EPP, gateway, IPP ...) is shared
    serving overhead -> reserved value OVERHEAD (paper 2.3.3);
  * OpenCost's ``__idle__`` (node capacity no pod requested) -> IDLE.

    GET <opencost>/allocation/compute?window=<start>,<end>&aggregate=namespace,pod
        &step=<grain>s&resolution=1m&includeIdle=true&accumulate=false
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

IDLE = "__idle__"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s: str) -> float:
    return datetime.strptime(s.replace(".000", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def fetch_allocations(url: str, start: float, end: float, step_s: int) -> list[dict]:
    q = urllib.parse.urlencode({"window": f"{_iso(start)},{_iso(end)}", "aggregate": "namespace,pod",
                                "step": f"{step_s}s", "resolution": "1m", "includeIdle": "true",
                                "accumulate": "false"})
    with urllib.request.urlopen(f"{url.rstrip('/')}/allocation/compute?{q}", timeout=120) as r:
        body = json.load(r)
    if body.get("code") != 200:
        raise RuntimeError(f"OpenCost: {body.get('code')} {body.get('message')}")
    out = []
    for step in body.get("data") or []:
        for key, a in (step or {}).items():
            props = a.get("properties") or {}
            out.append({
                "key": key,
                "namespace": props.get("namespace", ""),
                "pod": props.get("pod", key),
                "start": _ts(a["window"]["start"]),
                "end": _ts(a["window"]["end"]),
                "gpuHours": a.get("gpuHours", 0.0) or 0.0,
                "gpuCost": a.get("gpuCost", 0.0) or 0.0,
                "cpuCost": a.get("cpuCost", 0.0) or 0.0,
                "ramCost": a.get("ramCost", 0.0) or 0.0,
                "totalCost": a.get("totalCost", 0.0) or 0.0,
            })
    return out


def cost_rows(cfg: dict, allocations: list[dict]) -> list[dict]:
    """FOCUS rows for the inference namespace + idle. ``_p`` = period start (unix s)."""
    c = cfg["cost"]
    ns = c.get("namespace", "llm-d")
    exclude = tuple(c.get("exclude_pod_prefixes", []))
    rows = []
    for a in allocations:
        idle = a["key"] == IDLE or a["pod"] == IDLE
        if not idle and a["namespace"] != ns:
            continue  # monitoring, OpenCost itself, kube-system: outside this demo's scope
        if not idle and exclude and a["pod"].startswith(exclude):
            continue  # the demo's own client (driver Job) is not serving infrastructure
        rid = IDLE if idle else a["pod"]
        rows.append({
            "_p": a["start"], "_end": a["end"],
            "ServiceProviderName": c["service_provider_name"], "BillingAccountId": c["billing_account_id"],
            "SubAccountId": c["sub_account_id"], "ServiceName": c["service_name"], "ResourceId": rid,
            "SkuPriceDetails.ModelId": None, "ChargePeriodStart": _iso(a["start"]),
            "ChargePeriodEnd": _iso(a["end"]), "ChargeCategory": "Usage", "PricingCategory": "Committed",
            "ConsumedQuantity": a["gpuHours"], "ConsumedUnit": "GPU Hours",
            "BilledCost": a["totalCost"], "EffectiveCost": a["totalCost"],
            "x_GpuCost": a["gpuCost"], "x_CpuCost": a["cpuCost"], "x_RamCost": a["ramCost"],
        })
    return rows
