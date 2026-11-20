"""Agent driver: runs the demo workloads against the llm-d entry point.

    python3 -m tokeneconomics.driver --phase baseline --duration 300 --concurrency 12

Every model call is one trace. The driver opens it with a root span that
carries the value-attribution lineage keys (``focus.workload.id``,
``focus.task.id``, ``focus.outcome.id``) and forwards the same keys as W3C
baggage, so Envoy -> EPP -> vLLM spans join the trace. UNLINKED playground
calls carry no keys and no traceparent: Envoy roots their trace.

Outputs (JSON lines, appended) under ``--out``:
  phases.jsonl    one row per phase (name, start, end, EPP config note)
  requests.jsonl  one row per model call (trace id, usage from the response)
  tasks.jsonl     one row per Task with its gate results
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import threading
import time
import urllib.request

from . import otlp
from .workloads import (SUPPORT_RETRY, SUPPORT_STEP2, TaskResult, judge_support, judge_triage, make_alert,
                        make_ticket, playground_messages, support_messages, triage_messages)


class Driver:
    def __init__(self, args):
        self.args = args
        self.model = args.model
        self.url = args.endpoint.rstrip("/") + "/v1/chat/completions"
        self.exporter = otlp.SpanExporter(args.otlp)
        self.lock = threading.Lock()
        os.makedirs(args.out, exist_ok=True)
        self.f_req = open(os.path.join(args.out, "requests.jsonl"), "a")
        self.f_task = open(os.path.join(args.out, "tasks.jsonl"), "a")
        self.counter = 0
        # Unique per driver process: in a container the PID is always 1, so a
        # PID-based id would collide across runs and pods.
        self.run_id = os.urandom(3).hex()
        self.stats = {"tasks": 0, "requests": 0, "errors": 0}

    # ------------------------------------------------------------------ io
    def _write(self, f, row: dict) -> None:
        with self.lock:
            f.write(json.dumps(row) + "\n")
            f.flush()

    def _next_id(self, prefix: str) -> str:
        with self.lock:
            self.counter += 1
            return f"{prefix}-{self.args.phase}-{self.run_id}-{self.counter:05d}"

    def call(self, messages: list[dict], max_tokens: int, lineage: dict | None, step: str) -> tuple[str, dict]:
        """One chat completion. ``lineage`` None -> UNLINKED (no keys, no traceparent)."""
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": self.args.temperature}
        headers = {"Content-Type": "application/json"}
        trace_id = span_id = None
        if lineage is not None:
            trace_id, span_id = otlp.new_trace_id(), otlp.new_span_id()
            headers["traceparent"] = otlp.traceparent(trace_id, span_id)
            headers["baggage"] = otlp.baggage_header(lineage)
        start = otlp.now_ns()
        text, usage, err = "", {}, None
        try:
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=self.args.timeout) as r:
                resp = json.load(r)
            text = resp["choices"][0]["message"].get("content") or ""
            usage = resp.get("usage") or {}
        except Exception as e:  # count, keep going
            err = f"{type(e).__name__}: {e}"[:200]
        end = otlp.now_ns()
        cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        if lineage is not None:
            attrs = dict(lineage)
            attrs.update({
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": self.model,
                "gen_ai.usage.input_tokens": usage.get("prompt_tokens"),
                "gen_ai.usage.output_tokens": usage.get("completion_tokens"),
                "gen_ai.usage.cache_read.input_tokens": cached,
                "demo.step": step,
                "demo.phase": self.args.phase,
            })
            self.exporter.span(trace_id=trace_id, span_id=span_id, name=f"agent.{step}",
                               start_ns=start, end_ns=end, attrs=attrs, error=err is not None)
        row = {"ts": start / 1e9, "dur_s": (end - start) / 1e9, "phase": self.args.phase,
               "trace_id": trace_id, "step": step, "error": err,
               "workload": (lineage or {}).get("focus.workload.id", "UNLINKED"),
               "task_id": (lineage or {}).get("focus.task.id", "UNLINKED"),
               "outcome_id": (lineage or {}).get("focus.outcome.id", "UNLINKED"),
               "prompt_tokens": usage.get("prompt_tokens", 0),
               "completion_tokens": usage.get("completion_tokens", 0),
               "cached_tokens": cached}
        self._write(self.f_req, row)
        with self.lock:
            self.stats["requests"] += 1
            self.stats["errors"] += err is not None
        return text, row

    # ----------------------------------------------------------- workloads
    def run_support(self, rng: random.Random) -> TaskResult:
        ticket_id = self._next_id("ticket")
        t = make_ticket(rng, ticket_id)
        task = TaskResult(task_id=f"task-{ticket_id}", workload="support_bot", outcome_id=ticket_id,
                          task_type="refund_calc", start=time.time())
        lin = {"focus.workload.id": "support_bot", "focus.task.id": task.task_id,
               "focus.outcome.id": ticket_id}
        msgs = support_messages(t)
        reply, _ = self.call(msgs, 128, lin, "investigate")
        task.requests += 1
        msgs += [{"role": "assistant", "content": reply}, {"role": "user", "content": SUPPORT_STEP2}]
        refund = None
        for attempt in range(1 + self.args.max_retries):
            task.attempts = attempt + 1
            reply, _ = self.call(msgs, 64, lin, "compute" if attempt == 0 else "retry")
            task.requests += 1
            ok, refund = judge_support(t, reply)
            if ok:
                task.task_quality_bar_met = True
                break
            msgs += [{"role": "assistant", "content": reply}, {"role": "user", "content": SUPPORT_RETRY}]
        task.outcome_quality_bar_met = task.task_quality_bar_met and refund is not None and \
            math.isclose(refund, t.refund, abs_tol=0.011)
        task.detail = {"expected_refund": t.refund, "refund": refund, "plan": t.plan}
        task.end = time.time()
        return task

    def run_triage(self, rng: random.Random) -> TaskResult:
        alert_id = self._next_id("alert")
        a = make_alert(rng, alert_id)
        task = TaskResult(task_id=f"task-{alert_id}", workload="triage_bot", outcome_id=alert_id,
                          task_type="alert_triage", start=time.time())
        lin = {"focus.workload.id": "triage_bot", "focus.task.id": task.task_id,
               "focus.outcome.id": alert_id}
        reply, _ = self.call(triage_messages(a), 48, lin, "triage")
        task.requests = task.attempts = 1
        ok, v = judge_triage(a, reply)
        task.task_quality_bar_met = ok
        task.outcome_quality_bar_met = bool(ok and v["severity"] == a.severity and v["component"] == a.component)
        task.detail = {"expected": [a.severity, a.component], "got": v}
        task.end = time.time()
        return task

    def worker(self, seed: int, deadline: float) -> None:
        rng = random.Random(seed)
        mix = self.args.mix
        while time.time() < deadline:
            r = rng.random()
            if r < mix["support_bot"]:
                task = self.run_support(rng)
            elif r < mix["support_bot"] + mix["triage_bot"]:
                task = self.run_triage(rng)
            else:
                self.call(playground_messages(rng), 96, None, "playground")
                continue
            row = dict(task.__dict__)
            row["phase"] = self.args.phase
            self._write(self.f_task, row)
            with self.lock:
                self.stats["tasks"] += 1

    def run(self) -> None:
        start = time.time()
        deadline = start + self.args.duration
        threads = [threading.Thread(target=self.worker, args=(self.args.seed * 1000 + i, deadline))
                   for i in range(self.args.concurrency)]
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            time.sleep(10)
            with self.lock:
                s = dict(self.stats)
            print(f"[{self.args.phase}] t+{time.time() - start:5.0f}s tasks={s['tasks']} "
                  f"requests={s['requests']} errors={s['errors']}", flush=True)
        end = time.time()
        self.exporter.close()
        with open(os.path.join(self.args.out, "phases.jsonl"), "a") as f:
            f.write(json.dumps({"phase": self.args.phase, "start": start, "end": end,
                                "note": self.args.note, "concurrency": self.args.concurrency,
                                "spans_dropped": self.exporter.dropped}) + "\n")
        print(f"phase {self.args.phase} done in {end - start:.0f}s: {self.stats}, "
              f"spans dropped={self.exporter.dropped}")


def parse_mix(s: str) -> dict:
    mix = {"support_bot": 0.0, "triage_bot": 0.0, "unlinked": 0.0}
    for part in s.split(","):
        k, v = part.split("=")
        mix[k.strip()] = float(v)
    total = sum(mix.values())
    return {k: v / total for k, v in mix.items()}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--phase", required=True, help="label, e.g. baseline or incident")
    p.add_argument("--note", default="", help="free text stored with the phase (e.g. EPP config)")
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--concurrency", type=int, default=12)
    p.add_argument("--mix", type=parse_mix, default=parse_mix("support_bot=0.5,triage_bot=0.4,unlinked=0.1"))
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--endpoint", default="http://127.0.0.1:8081")
    p.add_argument("--otlp", default="http://127.0.0.1:4318")
    p.add_argument("--model", default=os.environ.get("MODEL", "Qwen/Qwen2.5-1.5B-Instruct"))
    p.add_argument("--out", default="data")
    Driver(p.parse_args()).run()


if __name__ == "__main__":
    main()
