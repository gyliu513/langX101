"""Build the five value-attribution datasets from traces + the driver's records.

    python3 -m tokeneconomics.build --data data --config configs/demo.toml

Inputs
  * Jaeger (``--jaeger``): every trace in the run window. The leaf span for the
    GPU consumption scope is vLLM's own ``llm_request`` span; the lineage keys
    come from the driver's root span on the same trace ("enterprise enrichment",
    paper section 2.2.2 item 4: we join on trace_id at ingest, nothing upstream
    has to emit ``focus.*``). Traces with no driver root are UNLINKED.
  * ``data/tasks.jsonl`` / ``data/phases.jsonl`` written by the driver.

Outputs (``data/``): ``tokeneconomics.db`` (SQLite) and one CSV per dataset:
  cost_and_usage, telemetry, task, outcome, value  (+ kpi views, see kpis.sql)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import time
import tomllib
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- traces
def fetch_traces(jaeger: str, start: float, end: float, slice_s: int = 15, limit: int = 3000,
                 services: tuple = ("vllm-0", "vllm-1")) -> dict:
    """All traces touching a vLLM replica in [start, end], deduplicated by trace id."""
    traces = {}
    for service in services:
        t = start
        while t < end:
            q = urllib.parse.urlencode({"service": service, "operation": "llm_request",
                                        "start": int(t * 1e6), "end": int(min(t + slice_s, end) * 1e6),
                                        "limit": limit})
            with urllib.request.urlopen(f"{jaeger}/api/traces?{q}", timeout=60) as r:
                data = json.load(r).get("data") or []
            if len(data) >= limit:
                print(f"WARNING: {service} slice at {iso(t)} hit limit={limit}; lower --slice")
            for tr in data:
                traces[tr["traceID"]] = tr
            t += slice_s
    return traces


def tags(span: dict) -> dict:
    return {t["key"]: t["value"] for t in span.get("tags", [])}


def leaf_rows(traces: dict) -> list[dict]:
    """One row per vLLM llm_request span, enriched with the trace's lineage keys."""
    rows = []
    for tr in traces.values():
        procs = {k: v["serviceName"] for k, v in tr["processes"].items()}
        # On Kubernetes the replicas share a service name; the pod comes from the
        # OTel resource attribute k8s.pod.name (process tags in Jaeger).
        pods = {k: next((t["value"] for t in v.get("tags", []) if t["key"] == "k8s.pod.name"), None)
                for k, v in tr["processes"].items()}
        root = None
        for s in tr["spans"]:
            if procs[s["processID"]] == "agent-driver":
                root = tags(s)
        for s in tr["spans"]:
            svc = procs[s["processID"]]
            if not (svc.startswith("vllm") and s["operationName"] == "llm_request"):
                continue
            a = tags(s)
            lin = root or {}
            prefill = float(a.get("gen_ai.latency.time_in_model_prefill") or 0)
            decode = float(a.get("gen_ai.latency.time_in_model_decode") or 0)
            rows.append({
                "trace_id": tr["traceID"],
                "ts": s["startTime"] / 1e6,
                "replica": pods.get(s["processID"]) or svc,
                "workload": lin.get("focus.workload.id", "UNLINKED"),
                "task": lin.get("focus.task.id", "UNLINKED"),
                "outcome": lin.get("focus.outcome.id", "UNLINKED"),
                "input": int(a.get("gen_ai.usage.prompt_tokens") or 0),
                "output": int(a.get("gen_ai.usage.completion_tokens") or 0),
                # vLLM's span has no cached-token count; the client saw it in
                # usage.prompt_tokens_details and put it on the root span.
                "cache_read": int(lin.get("gen_ai.usage.cache_read.input_tokens") or 0),
                "prefill_s": prefill,
                "decode_s": decode,
                "duration_ms": s["duration"] / 1e3,
            })
    return rows


# --------------------------------------------------------------- datasets
SCHEMA = {
    "cost_and_usage": """ServiceProviderName TEXT, BillingAccountId TEXT, SubAccountId TEXT, ServiceName TEXT,
        ResourceId TEXT, "SkuPriceDetails.ModelId" TEXT, ChargePeriodStart TEXT, ChargePeriodEnd TEXT,
        ChargeCategory TEXT, PricingCategory TEXT, ConsumedQuantity REAL, ConsumedUnit TEXT,
        BilledCost REAL, EffectiveCost REAL, x_GpuCost REAL, x_CpuCost REAL, x_RamCost REAL""",
    "telemetry": """TaskId TEXT, OutcomeId TEXT, WorkloadId TEXT, ServiceProviderName TEXT, BillingAccountId TEXT,
        ResourceId TEXT, ServiceName TEXT, SubAccountId TEXT, ModelId TEXT, TelemetryPeriodStart TEXT,
        TelemetryPeriodEnd TEXT, InvocationCount INTEGER, InputTokenCount INTEGER, OutputTokenCount INTEGER,
        CacheReadTokenCount INTEGER, CacheWriteTokenCount INTEGER, TotalDurationMs REAL, ActivityWeight REAL,
        x_ServingReplica TEXT, x_PrefillSeconds REAL, x_DecodeSeconds REAL, x_AllocatedCost REAL, x_Phase TEXT""",
    "task": """TaskId TEXT, OutcomeId TEXT, WorkloadId TEXT, UpstreamOutcomeId TEXT, TaskPeriodStart TEXT,
        TaskPeriodEnd TEXT, TaskType TEXT, TaskName TEXT, TaskQualityBarMet INTEGER, AttemptedTaskCount INTEGER,
        QualifiedTaskCount INTEGER, TaskUnit TEXT, BaselineTaskQuantity REAL, ObservedTaskQuantity REAL,
        TaskFrictionQuantity REAL, TaskReworkPenaltyQuantity REAL, NetTaskQuantity REAL,
        x_Phase TEXT, x_Attempts INTEGER, x_Requests INTEGER""",
    "outcome": """OutcomeId TEXT, WorkloadId TEXT, OutcomeEntryNumber INTEGER, OutcomePeriodStart TEXT,
        OutcomePeriodEnd TEXT, OutcomeRecordedDateTime TEXT, OutcomeStatus TEXT, OutcomeSettledDateTime TEXT,
        OutcomeType TEXT, OutcomeName TEXT, WorkloadName TEXT, OutcomeQualityBarMet INTEGER,
        AttemptedOutcomeCount INTEGER, QualifiedOutcomeCount INTEGER, OutcomeUnit TEXT,
        BaselineOutcomeQuantity REAL, ObservedOutcomeQuantity REAL, OutcomeFrictionQuantity REAL,
        OutcomeReworkPenaltyQuantity REAL, NetOutcomeQuantity REAL, OutcomeEntryNotes TEXT, x_Phase TEXT""",
    "value": """WorkloadId TEXT, OutcomeId TEXT, ValueClaimId TEXT, ValuePeriodStart TEXT, ValuePeriodEnd TEXT,
        StakeholderRoleName TEXT, ValueCategoryName TEXT, ConversionMultiplier REAL, ValueUnit TEXT,
        ValueStatus TEXT, ValueDestination TEXT, AttestorId TEXT, AttestorRoleName TEXT, AttestedDateTime TEXT,
        EvidenceSystemName TEXT, EvidenceId TEXT, OutcomeCutoffDateTime TEXT, RealizedValue REAL,
        EstimatedValue REAL, PlannedValue REAL, x_Phase TEXT""",
}

WORKLOAD_NAMES = {"support_bot": "Autonomous Billing Dispute Agent", "triage_bot": "Alert Triage Copilot"}


def static_cost_rows(cfg: dict, t0: float, t1: float) -> list[dict]:
    """A synthesized FOCUS bill: one row per charge period for one GPU (no-Kubernetes variant)."""
    c = cfg["cost"]
    grain = c["charge_period_seconds"]
    per_period_cost = c["gpu_hourly_usd"] * grain / 3600
    first, last = math.floor(t0 / grain) * grain, math.ceil(t1 / grain) * grain
    return [dict(_p=p, _end=p + grain, ServiceProviderName=c["service_provider_name"],
                 BillingAccountId=c["billing_account_id"], SubAccountId=c["sub_account_id"],
                 ServiceName=c["service_name"], ResourceId=c["resource_id"], **{"SkuPriceDetails.ModelId": None},
                 ChargePeriodStart=iso(p), ChargePeriodEnd=iso(p + grain), ChargeCategory="Usage",
                 PricingCategory="Committed", ConsumedQuantity=grain / 3600, ConsumedUnit=c["consumed_unit"],
                 BilledCost=per_period_cost, EffectiveCost=per_period_cost)
            for p in range(int(first), int(last), grain)]


def allocate(cfg: dict, cost_rows: list[dict], leaves: list[dict], scope_of) -> list[dict]:
    """Split every cost row over the telemetry of its (ResourceId, charge period).

    ``scope_of(leaf)`` gives the ResourceId a vLLM leaf span consumed. A cost row
    with no telemetry becomes IDLE when it is the cluster's idle capacity or a
    serving resource that served nothing, and OVERHEAD when it is a shared
    non-serving component (EPP, gateway ...), paper section 2.3.3.
    """
    c, aw = cfg["cost"], cfg["activity_weight"]
    serving_prefix = c.get("serving_pod_prefix")
    periods = sorted({(r["_p"], r["_end"]) for r in cost_rows})

    def period_of(ts):
        for p, e in periods:
            if p <= ts < e:
                return p
        return None

    groups = defaultdict(lambda: defaultdict(float))
    ends = dict(periods)
    for r in leaves:
        p = period_of(r["ts"])
        if p is None:
            continue
        g = groups[(scope_of(r), p, r["workload"], r["task"], r["outcome"], r["replica"])]
        g["n"] += 1
        g["input"] += r["input"]
        g["output"] += r["output"]
        g["cache_read"] += r["cache_read"]
        g["duration_ms"] += r["duration_ms"]
        g["prefill_s"] += r["prefill_s"]
        g["decode_s"] += r["decode_s"]

    def weight(g) -> float:
        if aw["method"] == "tokens":
            uncached = max(g["input"] - g["cache_read"], 0)
            return uncached * aw["uncached_input"] + g["cache_read"] * aw["cached_input"] + g["output"] * aw["output"]
        return g["prefill_s"] + g["decode_s"]

    total_w = defaultdict(float)
    for (rid, p, *_), g in groups.items():
        total_w[(rid, p)] += weight(g)
    cost_of = defaultdict(float)
    for r in cost_rows:
        cost_of[(r["ResourceId"], r["_p"])] += r["EffectiveCost"]

    def row(task, outcome, wl, rid, p, replica, alloc, g=None, w=0.0):
        g = g or defaultdict(float)
        return dict(TaskId=task, OutcomeId=outcome, WorkloadId=wl, ServiceProviderName=c["service_provider_name"],
                    BillingAccountId=c["billing_account_id"], ResourceId=rid, ServiceName=c["service_name"],
                    SubAccountId=c["sub_account_id"], ModelId=c["model_id"], TelemetryPeriodStart=iso(p),
                    TelemetryPeriodEnd=iso(ends[p]), InvocationCount=int(g["n"]), InputTokenCount=int(g["input"]),
                    OutputTokenCount=int(g["output"]), CacheReadTokenCount=int(g["cache_read"]),
                    CacheWriteTokenCount=None, TotalDurationMs=round(g["duration_ms"], 3),
                    ActivityWeight=round(w, 6), x_ServingReplica=replica, x_PrefillSeconds=round(g["prefill_s"], 6),
                    x_DecodeSeconds=round(g["decode_s"], 6), x_AllocatedCost=alloc)

    tel = []
    for (rid, p, wl, task, outcome, replica), g in sorted(groups.items()):
        w = weight(g)
        tw = total_w[(rid, p)]
        tel.append(row(task, outcome, wl, rid, p, replica, cost_of[(rid, p)] * w / tw if tw else 0.0, g, w))
    # Cost rows nobody's telemetry absorbed: keep them visible instead of dropping them.
    for (rid, p), cost in sorted(cost_of.items()):
        if total_w.get((rid, p)):
            continue
        serving = rid == c.get("resource_id") or (serving_prefix and rid.startswith(serving_prefix))
        kind = "IDLE" if (rid == "__idle__" or serving) else "OVERHEAD"
        tel.append(row(kind, kind, kind, rid, p, rid if serving else None, cost))
    return tel


def build_cost_and_telemetry(cfg: dict, leaves: list[dict], t0: float, t1: float):
    """No-Kubernetes variant: synthesized bill for one GPU shared by all replicas."""
    cost_rows = static_cost_rows(cfg, t0, t1)
    rid = cfg["cost"]["resource_id"]
    return cost_rows, allocate(cfg, cost_rows, leaves, lambda r: rid)


def build_task_outcome_value(cfg: dict, tasks: list[dict], tel: list[dict], phases: list[dict], now: float):
    win = cfg["settlement"]["window_seconds"]
    task_rows, outcome_rows, value_rows = [], [], []

    for t in tasks:
        w = cfg["workloads"][t["workload"]]
        passed = bool(t["task_quality_bar_met"])
        correct = bool(t["outcome_quality_bar_met"])
        base = w["baseline_minutes"]
        friction = w["friction_minutes"] if passed else 0.0
        rework = 0.0 if passed else w["task_rework_minutes"]
        observed = base if passed else 0.0
        task_rows.append(dict(TaskId=t["task_id"], OutcomeId=t["outcome_id"], WorkloadId=t["workload"],
                              UpstreamOutcomeId=None, TaskPeriodStart=iso(t["start"]), TaskPeriodEnd=iso(t["end"]),
                              TaskType=w["task_type"], TaskName=None, TaskQualityBarMet=int(passed),
                              AttemptedTaskCount=1, QualifiedTaskCount=int(passed), TaskUnit="minutes",
                              BaselineTaskQuantity=base, ObservedTaskQuantity=observed,
                              TaskFrictionQuantity=friction, TaskReworkPenaltyQuantity=rework,
                              NetTaskQuantity=observed - friction - rework, x_Phase=t["phase"],
                              x_Attempts=t["attempts"], x_Requests=t["requests"]))

        settled = now >= t["end"] + win
        # Post-delivery recall: delivered (Gate 1 passed) but wrong (Gate 2 failed).
        recalled = passed and not correct
        post_rework = w["outcome_rework_minutes"] if recalled else 0.0
        if w["outcome_unit"] == "minutes":
            o_base, o_obs = base, (base if correct else 0.0)
            o_fric, o_rework = friction, rework + post_rework       # rolled up from Task + recall
            net = o_obs - o_fric - o_rework
        else:  # discrete unit: minutes cannot be subtracted, monetize them in Value
            o_base, o_obs, o_fric, o_rework = None, float(passed), 0.0, 0.0
            net = float(correct)
        note = None
        if recalled:
            note = "refund wrong: ticket reopened" if t["workload"] == "support_bot" else "wrong label: re-escalated"
        elif not passed:
            note = "agent gave up: handed to a human"
        outcome_rows.append(dict(OutcomeId=t["outcome_id"], WorkloadId=t["workload"], OutcomeEntryNumber=1,
                                 OutcomePeriodStart=iso(t["start"]), OutcomePeriodEnd=iso(t["end"] + win),
                                 OutcomeRecordedDateTime=iso(now), OutcomeStatus="Settled" if settled else "Pending",
                                 OutcomeSettledDateTime=iso(t["end"] + win) if settled else None,
                                 OutcomeType=w["outcome_type"], OutcomeName=None,
                                 WorkloadName=WORKLOAD_NAMES.get(t["workload"]), OutcomeQualityBarMet=int(correct),
                                 AttemptedOutcomeCount=1, QualifiedOutcomeCount=int(correct),
                                 OutcomeUnit=w["outcome_unit"], BaselineOutcomeQuantity=o_base,
                                 ObservedOutcomeQuantity=o_obs, OutcomeFrictionQuantity=o_fric,
                                 OutcomeReworkPenaltyQuantity=o_rework, NetOutcomeQuantity=net,
                                 OutcomeEntryNotes=note, x_Phase=t["phase"]))

        value = net * w["conversion_multiplier"]
        planned = w["planned_qualified_rate"] * (w["conversion_multiplier"] *
                                                  (base if w["outcome_unit"] == "minutes" else 1.0))
        common = dict(WorkloadId=t["workload"], OutcomeId=t["outcome_id"], ValuePeriodStart=iso(t["start"]),
                      ValuePeriodEnd=iso(t["end"] + win), StakeholderRoleName=w["stakeholder"], ValueUnit="USD",
                      ValueStatus="Reported", ValueDestination=None, AttestorId=None, AttestorRoleName=None,
                      AttestedDateTime=None, EvidenceSystemName="tokeneconomics-demo",
                      EvidenceId=t["task_id"], OutcomeCutoffDateTime=iso(t["end"] + win) if settled else None,
                      x_Phase=t["phase"])
        value_rows.append(dict(common, ValueClaimId=f"{t['outcome_id']}:{w['stakeholder']}:main",
                               ValueCategoryName=w["value_category"], ConversionMultiplier=w["conversion_multiplier"],
                               RealizedValue=value if settled else None, EstimatedValue=value, PlannedValue=planned))
        if w["outcome_unit"] != "minutes":
            # Friction / rework in minutes against a discrete unit: a separate,
            # negative claim under the same stakeholder lens (paper 2.4.3).
            labor = -(friction + rework + post_rework) * w["labor_usd_per_minute"]
            value_rows.append(dict(common, ValueClaimId=f"{t['outcome_id']}:{w['stakeholder']}:labor",
                                   ValueCategoryName="Friction and Rework", ConversionMultiplier=w["labor_usd_per_minute"],
                                   RealizedValue=labor if settled else None, EstimatedValue=labor, PlannedValue=None))

    # UNLINKED Task: one row per phase so Scrap Rate can report it as its own line.
    unlinked = defaultdict(int)
    for r in tel:
        if r["TaskId"] == "UNLINKED":
            unlinked[r["x_Phase"]] += r["InvocationCount"]
    for ph, n in unlinked.items():
        task_rows.append(dict(TaskId="UNLINKED", OutcomeId="UNLINKED", WorkloadId="UNLINKED", UpstreamOutcomeId=None,
                              TaskPeriodStart=None, TaskPeriodEnd=None, TaskType="unlinked", TaskName=None,
                              TaskQualityBarMet=0, AttemptedTaskCount=n, QualifiedTaskCount=0, TaskUnit="minutes",
                              BaselineTaskQuantity=None, ObservedTaskQuantity=0, TaskFrictionQuantity=0,
                              TaskReworkPenaltyQuantity=0, NetTaskQuantity=0, x_Phase=ph, x_Attempts=0, x_Requests=n))
    return task_rows, outcome_rows, value_rows


def write(db: sqlite3.Connection, out: str, name: str, rows: list[dict]) -> None:
    db.execute(f"DROP TABLE IF EXISTS {name}")
    db.execute(f"CREATE TABLE {name} ({SCHEMA[name]})")
    cols = [c.strip().split()[0] for c in SCHEMA[name].split(",")]
    keys = [c.strip('"') for c in cols]
    db.executemany(f"INSERT INTO {name} VALUES ({','.join('?' * len(cols))})",
                   [[r.get(k) for k in keys] for r in rows])
    with open(os.path.join(out, f"{name}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        w.writerows([[r.get(k) for k in keys] for r in rows])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="data")
    p.add_argument("--config", default="configs/demo.toml")
    p.add_argument("--jaeger", default="http://127.0.0.1:16686")
    p.add_argument("--harvest", action="store_true",
                   help="only fetch the latest phase's vLLM leaf spans from Jaeger into leaves.jsonl and exit "
                        "(run right after each phase: an in-memory Jaeger evicts old traces)")
    p.add_argument("--window", default=None, help="with --harvest: START,END unix seconds instead of the last phase")
    p.add_argument("--opencost", default=None, help="OpenCost API URL (overrides [cost] opencost_url)")
    p.add_argument("--now", type=float, default=None, help="evaluate settlement as of this unix time")
    args = p.parse_args()

    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    services = tuple(cfg.get("traces", {}).get("vllm_services", ["vllm-0", "vllm-1"]))
    leaves_path = os.path.join(args.data, "leaves.jsonl")
    phases = read_jsonl(os.path.join(args.data, "phases.jsonl"))

    if args.harvest:
        if args.window:
            a, b = (float(x) for x in args.window.split(","))
        elif phases:
            a, b = phases[-1]["start"] - 5, phases[-1]["end"] + 30
        else:
            raise SystemExit("--harvest needs --window or a phases.jsonl")
        leaves = leaf_rows(fetch_traces(args.jaeger, a, b, services=services))
        os.makedirs(args.data, exist_ok=True)
        with open(leaves_path, "a") as f:
            for r in leaves:
                f.write(json.dumps(r) + "\n")
        print(f"harvested {len(leaves)} vLLM leaf spans in [{iso(a)}, {iso(b)}] -> {leaves_path}")
        return

    tasks = read_jsonl(os.path.join(args.data, "tasks.jsonl"))
    requests = read_jsonl(os.path.join(args.data, "requests.jsonl"))
    if not phases:
        raise SystemExit("no phases.jsonl: run the driver first")
    t0, t1 = min(ph["start"] for ph in phases), max(ph["end"] for ph in phases)
    now = args.now or time.time()

    if os.path.exists(leaves_path):
        # The harvester's windows overlap, and a trace can be harvested before the
        # client's root span arrived: keep one row per span, preferring the
        # linked copy, and only spans inside the phase windows.
        best = {}
        for r in read_jsonl(leaves_path):
            k = (r["trace_id"], r["ts"])
            if k not in best or (best[k]["task"] == "UNLINKED" and r["task"] != "UNLINKED"):
                best[k] = r
        leaves = [r for r in best.values() if any(ph["start"] - 5 <= r["ts"] <= ph["end"] + 30 for ph in phases)]
        traces = {r["trace_id"] for r in leaves}
        print(f"using {len(leaves)} harvested leaf spans from {leaves_path} "
              f"({len(best) - len(leaves)} outside the phase windows dropped)")
    else:
        traces = fetch_traces(args.jaeger, t0 - 5, t1 + 30, services=services)
        leaves = leaf_rows(traces)
    linked_req = sum(1 for r in requests if r["trace_id"] and not r["error"])
    linked_leaf = sum(1 for r in leaves if r["task"] != "UNLINKED")
    print(f"traces={len(traces)} vLLM leaf spans={len(leaves)} (linked {linked_leaf} of {linked_req} "
          f"linked driver calls, unlinked {len(leaves) - linked_leaf})")

    if cfg["cost"].get("source", "static") == "opencost":
        from . import opencost
        grain = cfg["cost"]["charge_period_seconds"]
        first, last = math.floor(t0 / grain) * grain, math.ceil(t1 / grain) * grain
        allocs = opencost.fetch_allocations(args.opencost or cfg["cost"]["opencost_url"], first, last, grain)
        cost = opencost.cost_rows(cfg, allocs)
        tel = allocate(cfg, cost, leaves, lambda r: r["replica"])  # Consumption Scope = the pod
        print(f"opencost: {len(allocs)} allocations -> {len(cost)} cost rows in scope")
    else:
        cost, tel = build_cost_and_telemetry(cfg, leaves, t0, t1)
    # Phase of a telemetry row: from its Task when linked, else from the time
    # of its charge period (UNLINKED / IDLE rows).
    task_phase = {t["task_id"]: t["phase"] for t in tasks}
    grain = cfg["cost"]["charge_period_seconds"]
    for r in tel:
        if r["TaskId"] in task_phase:
            r["x_Phase"] = task_phase[r["TaskId"]]
            continue
        mid = datetime.strptime(r["TelemetryPeriodStart"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp() + grain / 2
        r["x_Phase"] = next((ph["phase"] for ph in phases if ph["start"] <= mid <= ph["end"]), "between-phases")
    task_rows, outcome_rows, value_rows = build_task_outcome_value(cfg, tasks, tel, phases, now)

    dbpath = os.path.join(args.data, "tokeneconomics.db")
    db = sqlite3.connect(dbpath)
    for name, rows in [("cost_and_usage", cost), ("telemetry", tel), ("task", task_rows),
                       ("outcome", outcome_rows), ("value", value_rows)]:
        write(db, args.data, name, rows)
    db.execute("DROP TABLE IF EXISTS phase")
    db.execute("CREATE TABLE phase (phase TEXT, start TEXT, end_ TEXT, note TEXT)")
    db.executemany("INSERT INTO phase VALUES (?,?,?,?)",
                   [(ph["phase"], iso(ph["start"]), iso(ph["end"]), ph.get("note", "")) for ph in phases])
    with open(os.path.join(HERE, "kpis.sql")) as f:
        db.executescript(f.read())
    db.commit()
    print(f"wrote {dbpath}: cost_and_usage={len(cost)} telemetry={len(tel)} task={len(task_rows)} "
          f"outcome={len(outcome_rows)} value={len(value_rows)}")


if __name__ == "__main__":
    main()
