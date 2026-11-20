"""Offline unit tests for the token-economics demo (no GPU, no Jaeger needed)."""

import os
import random
import sqlite3
import tomllib

import pytest

from tokeneconomics import build, otlp
from tokeneconomics.workloads import (Alert, judge_support, judge_triage, make_ticket, parse_json,
                                      refund_calculator)

HERE = os.path.dirname(__file__)
CONFIG = os.path.join(HERE, "..", "nonk8s", "configs", "demo.toml")


@pytest.fixture
def cfg():
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


# ------------------------------------------------------------------- otlp
def test_traceparent_and_baggage():
    tid, sid = otlp.new_trace_id(), otlp.new_span_id()
    assert len(tid) == 32 and len(sid) == 16
    assert otlp.traceparent(tid, sid) == f"00-{tid}-{sid}-01"
    h = otlp.baggage_header({"focus.workload.id": "support_bot", "focus.task.id": "a b,c", "empty": ""})
    assert h == "focus.workload.id=support_bot,focus.task.id=a%20b%2Cc"


# -------------------------------------------------------------- workloads
def test_ticket_is_deterministic_and_refund_uses_latest_fee():
    a, b = make_ticket(random.Random(1), "t"), make_ticket(random.Random(1), "t")
    assert a == b
    assert a.fee in a.plan_fees
    assert a.refund == refund_calculator(a.fee, a.day, a.cycle)


def test_support_gate1_validates_against_the_record():
    t = make_ticket(random.Random(3), "t")
    ok, refund = judge_support(t, f'{{"amount_usd": {t.fee}, "cancel_day": {t.day}, "cycle_days": {t.cycle}}}')
    assert ok and refund == t.refund
    # an amount that is not an invoice of this plan fails Gate 1
    assert judge_support(t, f'{{"amount_usd": 1234.56, "cancel_day": {t.day}, "cycle_days": {t.cycle}}}') == (False, None)
    assert judge_support(t, "no json here") == (False, None)
    assert judge_support(t, '{"amount_usd": "x"}') == (False, None)


def test_support_stale_invoice_passes_gate1_but_gives_wrong_refund():
    # Gate 1 cannot tell an older invoice from the current one (finding F6).
    for seed in range(50):
        t = make_ticket(random.Random(seed), "t")
        older = [f for f in t.plan_fees if f != t.fee]
        if older:
            ok, refund = judge_support(t, f'{{"amount_usd": {older[0]}, "cancel_day": {t.day}, '
                                          f'"cycle_days": {t.cycle}}}')
            assert ok and refund != t.refund
            return
    pytest.fail("no ticket with more than one plan price")


def test_triage_gate_and_json_parsing():
    a = Alert("a1", "x", "P2", "db")
    ok, v = judge_triage(a, 'Sure: {"severity": "P2", "component": "db"} done')
    assert ok and v == {"severity": "P2", "component": "db"}
    assert judge_triage(a, '{"severity": "P9", "component": "db"}')[0] is False
    assert parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert parse_json("[1, 2]") is None


# ------------------------------------------------------------------ build
def leaf(ts, workload, task, prefill, decode, inp=100, out=10, cache=0, replica="vllm-0"):
    return {"ts": ts, "replica": replica, "workload": workload, "task": task, "outcome": task.replace("task-", ""),
            "input": inp, "output": out, "cache_read": cache, "prefill_s": prefill, "decode_s": decode,
            "duration_ms": (prefill + decode) * 1000}


def test_allocation_covers_the_whole_bill_and_keeps_idle(cfg):
    g = cfg["cost"]["charge_period_seconds"]
    t0 = 1_800_000_000 - 1_800_000_000 % g
    leaves = [leaf(t0 + 1, "support_bot", "task-1", 0.3, 0.7),      # weight 1.0
              leaf(t0 + 2, "triage_bot", "task-2", 0.1, 0.9),       # weight 1.0
              leaf(t0 + 3, "UNLINKED", "UNLINKED", 1.0, 1.0)]       # weight 2.0
    # three periods, the last one has no activity -> IDLE
    cost, tel = build.build_cost_and_telemetry(cfg, leaves, t0, t0 + 3 * g - 1)
    per_period = cfg["cost"]["gpu_hourly_usd"] * g / 3600
    assert len(cost) == 3
    assert sum(r["EffectiveCost"] for r in cost) == pytest.approx(3 * per_period)
    assert sum(r["x_AllocatedCost"] for r in tel) == pytest.approx(3 * per_period)
    by_task = {r["TaskId"]: r["x_AllocatedCost"] for r in tel if r["TelemetryPeriodStart"] == build.iso(t0)}
    assert by_task["task-1"] == pytest.approx(per_period / 4)
    assert by_task["UNLINKED"] == pytest.approx(per_period / 2)
    assert sum(1 for r in tel if r["WorkloadId"] == "IDLE") == 2


def test_token_weighting(cfg):
    cfg["activity_weight"]["method"] = "tokens"
    g = cfg["cost"]["charge_period_seconds"]
    t0 = 1_800_000_000 - 1_800_000_000 % g
    _, tel = build.build_cost_and_telemetry(cfg, [leaf(t0 + 1, "w", "task-1", 0, 0, inp=1000, out=10, cache=800)],
                                            t0, t0 + g - 1)
    aw = cfg["activity_weight"]
    assert tel[0]["ActivityWeight"] == pytest.approx(200 * aw["uncached_input"] + 800 * aw["cached_input"]
                                                     + 10 * aw["output"])


def task(workload, tid, passed, correct, end):
    return {"task_id": f"task-{tid}", "workload": workload, "outcome_id": tid, "start": end - 5, "end": end,
            "attempts": 1, "requests": 2, "task_quality_bar_met": passed, "outcome_quality_bar_met": correct,
            "phase": "p"}


def test_outcome_and_value_rules(cfg):
    now = 1_800_000_000
    win = cfg["settlement"]["window_seconds"]
    tasks = [task("support_bot", "ok", True, True, now - win - 10),      # settled, deflected
             task("support_bot", "reopened", True, False, now - win - 10),  # settled, recalled
             task("triage_bot", "pending", True, True, now - 1)]           # still Pending
    t_rows, o_rows, v_rows = build.build_task_outcome_value(cfg, tasks, [], [], now)
    o = {r["OutcomeId"]: r for r in o_rows}
    assert o["ok"]["OutcomeStatus"] == "Settled" and o["ok"]["QualifiedOutcomeCount"] == 1
    assert o["reopened"]["OutcomeQualityBarMet"] == 0 and o["reopened"]["OutcomeEntryNotes"].startswith("refund wrong")
    assert o["pending"]["OutcomeStatus"] == "Pending" and o["pending"]["OutcomeSettledDateTime"] is None
    sb = cfg["workloads"]["support_bot"]
    labor = {r["OutcomeId"]: r["EstimatedValue"] for r in v_rows if r["ValueClaimId"].endswith(":labor")}
    assert labor["reopened"] == pytest.approx(-(sb["friction_minutes"] + sb["outcome_rework_minutes"])
                                              * sb["labor_usd_per_minute"])
    pending = [r for r in v_rows if r["OutcomeId"] == "pending"][0]
    assert pending["RealizedValue"] is None and pending["EstimatedValue"] > 0
    assert all(r["ValueStatus"] == "Reported" for r in v_rows)


def test_kpi_views_run(cfg, tmp_path):
    g = cfg["cost"]["charge_period_seconds"]
    t0 = 1_800_000_000 - 1_800_000_000 % g
    leaves = [leaf(t0 + 1, "support_bot", "task-a", 0.5, 0.5), leaf(t0 + 2, "support_bot", "task-b", 0.5, 0.5)]
    cost, tel = build.build_cost_and_telemetry(cfg, leaves, t0, t0 + g - 1)
    for r in tel:
        r["x_Phase"] = "p"
    tasks = [task("support_bot", "a", True, True, t0 + 5), task("support_bot", "b", True, False, t0 + 5)]
    t_rows, o_rows, v_rows = build.build_task_outcome_value(cfg, tasks, tel, [], t0 + 10_000)
    db = sqlite3.connect(":memory:")
    for name, rows in [("cost_and_usage", cost), ("telemetry", tel), ("task", t_rows), ("outcome", o_rows),
                       ("value", v_rows)]:
        build.write(db, str(tmp_path), name, rows)
    with open(os.path.join(os.path.dirname(build.__file__), "kpis.sql")) as f:
        db.executescript(f.read())
    db.row_factory = sqlite3.Row
    w = dict(db.execute("SELECT * FROM kpi_workload").fetchone())
    assert w["tasks"] == 2 and w["q_outcomes"] == 1
    assert w["cpqo"] == pytest.approx(cfg["cost"]["gpu_hourly_usd"] * g / 3600)
    assert (tmp_path / "telemetry.csv").exists()


# --------------------------------------------------------------- opencost
K8S_CONFIG = os.path.join(HERE, "..", "k8s", "demo-k8s.toml")


def test_opencost_rows_and_per_pod_allocation():
    from tokeneconomics import opencost
    with open(K8S_CONFIG, "rb") as f:
        kcfg = tomllib.load(f)
    t0 = 1_800_000_000 - 1_800_000_000 % 60

    def alloc(key, ns, pod, cost, gpu_h=0.0, start=t0):
        return {"key": key, "namespace": ns, "pod": pod, "start": start, "end": start + 60, "gpuHours": gpu_h,
                "gpuCost": cost, "cpuCost": 0.0, "ramCost": 0.0, "totalCost": cost}

    allocs = [alloc("llm-d/precise-prefix-vllm-a", "llm-d", "precise-prefix-vllm-a", 0.02, 1 / 60),
              alloc("llm-d/precise-prefix-vllm-b", "llm-d", "precise-prefix-vllm-b", 0.02, 1 / 60),
              alloc("llm-d/llm-d-epp-x", "llm-d", "llm-d-epp-x", 0.001),
              alloc("llm-d/te-driver-baseline-x", "llm-d", "te-driver-baseline-x", 0.005),   # the client: excluded
              alloc("llm-d-monitoring/prom", "llm-d-monitoring", "prom", 0.003),           # other namespace: excluded
              alloc("__idle__", "", "__idle__", 0.04)]
    rows = opencost.cost_rows(kcfg, allocs)
    assert sorted(r["ResourceId"] for r in rows) == ["__idle__", "llm-d-epp-x", "precise-prefix-vllm-a",
                                                    "precise-prefix-vllm-b"]
    # pod a served two tasks; pod b served nothing in this period
    leaves = [leaf(t0 + 1, "support_bot", "task-1", 0.1, 0.2, replica="precise-prefix-vllm-a"),
              leaf(t0 + 2, "triage_bot", "task-2", 0.3, 0.4, replica="precise-prefix-vllm-a")]
    tel = build.allocate(kcfg, rows, leaves, lambda r: r["replica"])
    by = {(r["TaskId"], r["ResourceId"]): r["x_AllocatedCost"] for r in tel}
    assert by[("task-1", "precise-prefix-vllm-a")] == pytest.approx(0.02 * 0.3 / 1.0)
    assert by[("task-2", "precise-prefix-vllm-a")] == pytest.approx(0.02 * 0.7 / 1.0)
    assert by[("IDLE", "precise-prefix-vllm-b")] == pytest.approx(0.02)       # allocated but unused
    assert by[("IDLE", "__idle__")] == pytest.approx(0.04)                    # never allocated
    assert by[("OVERHEAD", "llm-d-epp-x")] == pytest.approx(0.001)            # shared serving component
    assert sum(r["x_AllocatedCost"] for r in tel) == pytest.approx(sum(r["EffectiveCost"] for r in rows))
