"""Minimal OpenTelemetry helpers with no SDK dependency.

The demo's agent driver is the *application* layer of the value-attribution
architecture (Tokenomics Foundation, "Value Attribution Data Architecture",
section 2.2.2 item 1): it knows which workload / task / outcome a model call
serves, so it

  * starts the trace (W3C ``traceparent``) so Envoy, the EPP and vLLM join it,
  * sends the lineage keys as W3C ``baggage`` (``focus.workload.id`` ...),
  * exports its own root span carrying the same keys as span attributes.

Spans are posted as OTLP/HTTP JSON to the collector, which keeps the demo
runnable with nothing but the Python standard library.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.parse
import urllib.request

SERVICE_NAME = "agent-driver"


def new_trace_id() -> str:
    return os.urandom(16).hex()


def new_span_id() -> str:
    return os.urandom(8).hex()


def traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


def baggage_header(keys: dict[str, str]) -> str:
    # W3C baggage: comma-separated key=value, values percent-encoded.
    return ",".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in keys.items() if v)


def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        v = {"boolValue": value}
    elif isinstance(value, int):
        v = {"intValue": str(value)}
    elif isinstance(value, float):
        v = {"doubleValue": value}
    else:
        v = {"stringValue": str(value)}
    return {"key": key, "value": v}


class SpanExporter:
    """Batches spans and posts them to ``<endpoint>/v1/traces`` in a thread."""

    def __init__(self, endpoint: str = "http://127.0.0.1:4318", batch: int = 64):
        self.url = endpoint.rstrip("/") + "/v1/traces"
        self.batch = batch
        self.q: queue.Queue = queue.Queue()
        self.dropped = 0
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def span(self, *, trace_id: str, span_id: str, name: str, start_ns: int, end_ns: int,
             attrs: dict, error: bool = False) -> None:
        self.q.put({
            "traceId": trace_id,
            "spanId": span_id,
            "name": name,
            "kind": 3,  # SPAN_KIND_CLIENT
            "startTimeUnixNano": str(start_ns),
            "endTimeUnixNano": str(end_ns),
            "attributes": [_attr(k, v) for k, v in attrs.items() if v is not None],
            "status": {"code": 2 if error else 1},
        })

    def _post(self, spans: list[dict]) -> None:
        body = {
            "resourceSpans": [{
                "resource": {"attributes": [_attr("service.name", SERVICE_NAME)]},
                "scopeSpans": [{"scope": {"name": "tokeneconomics-demo"}, "spans": spans}],
            }]
        }
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:  # never let telemetry break the workload
            self.dropped += len(spans)

    def _run(self) -> None:
        while True:
            item = self.q.get()
            if item is None:
                return
            spans = [item]
            while len(spans) < self.batch:
                try:
                    nxt = self.q.get(timeout=0.5)
                except queue.Empty:
                    break
                if nxt is None:
                    self._post(spans)
                    return
                spans.append(nxt)
            self._post(spans)

    def close(self) -> None:
        self.q.put(None)
        self._t.join(timeout=30)


def now_ns() -> int:
    return time.time_ns()
