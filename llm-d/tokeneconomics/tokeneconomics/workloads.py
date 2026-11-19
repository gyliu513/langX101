"""Synthetic but *checkable* AI workloads.

Each workload produces Tasks whose result can be judged automatically, so the
demo records real quality gates instead of made-up pass rates:

* ``support_bot``  - billing-dispute agent. Each ticket comes with a long,
  unique account history (~3k tokens). The agent first investigates (step 1),
  then computes a pro-rated refund as JSON (step 2) on the same conversation,
  so step 2 re-uses step 1's prefix: this is where KV-cache-aware routing pays.
  Gate 1 (Task)   : the reply is valid JSON with a plausible refund.
  Gate 2 (Outcome): the refund is correct to the cent; a wrong refund is a
                    ticket the customer re-opens inside the settlement window.
* ``triage_bot``   - alert triage. Short prompt, one call.
  Gate 1: valid JSON with allowed labels. Gate 2: labels match ground truth
  (a wrong label is an alert that gets re-escalated).
* ``UNLINKED`` traffic - ad-hoc playground calls with no lineage keys at all.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field

PLANS = {
    "Starter": [19.00, 21.00, 24.00],
    "Pro": [49.00, 54.00, 59.00],
    "Team": [129.00, 139.00, 149.00],
    "Enterprise": [499.00, 529.00, 549.00],
}
ADDONS = ["Extra storage 100GB", "Priority support", "SSO add-on", "Audit log export", "API overage"]


@dataclass
class Ticket:
    ticket_id: str
    history: str
    plan: str
    fee: float
    day: int
    cycle: int
    refund: float
    plan_fees: tuple = ()


def make_ticket(rng: random.Random, ticket_id: str, history_lines: int = 110) -> Ticket:
    plan = rng.choice(list(PLANS))
    cycle = rng.choice([28, 30, 31])
    day = rng.randint(2, cycle - 2)
    lines = []
    year, month = 2024, 1
    fee = None
    seen = set()
    for i in range(history_lines):
        month += 1
        if month > 12:
            month, year = 1, year + 1
        d = rng.randint(1, 28)
        if i % 4 == 0 or i == history_lines - 1:
            fee = rng.choice(PLANS[plan])
            seen.add(fee)
            item, amount = f"{plan} plan monthly subscription", fee
        else:
            item = rng.choice(ADDONS)
            amount = round(rng.uniform(3, 90), 2)
        status = rng.choice(["paid", "paid", "paid", "paid", "refunded", "credited"])
        lines.append(f"{year}-{month:02d}-{d:02d} | INV-{rng.randint(100000, 999999)} | "
                     f"{item} | ${amount:.2f} | {status}")
    history = "\n".join(lines)
    refund = round(fee * (cycle - day) / cycle, 2)
    return Ticket(ticket_id, history, plan, fee, day, cycle, refund, tuple(sorted(seen)))


SUPPORT_SYSTEM = (
    "You are a billing support agent. Read the customer's invoice history carefully. "
    "Refund policy: when a subscription is cancelled mid-cycle, refund the unused days pro rata "
    "using the MOST RECENT invoice amount for that plan: refund = amount * (cycle_days - "
    "cancel_day) / cycle_days, rounded to cents."
)


def support_messages(t: Ticket) -> list[dict]:
    return [
        {"role": "system", "content": SUPPORT_SYSTEM},
        {"role": "user", "content": (
            f"Ticket {t.ticket_id}. Invoice history (date | invoice | item | amount | status):\n"
            f"{t.history}\n\n"
            f"The customer cancelled the {t.plan} plan on day {t.day} of a {t.cycle}-day billing cycle. "
            f"Step 1: state the most recent {t.plan} plan invoice amount and the unused days. Be brief.")},
    ]


# Step 2 is a tool call: the model fills the arguments of a refund calculator
# (small models are bad at arithmetic; real agents use tools for it).
SUPPORT_STEP2 = ('Step 2: call the refund calculator. Reply with ONLY a JSON object, no prose: '
                 '{"ticket_id": "<id>", "amount_usd": <most recent plan invoice amount>, '
                 '"cancel_day": <day>, "cycle_days": <days>}')
SUPPORT_RETRY = ('The calculator rejected that call: the JSON was malformed or amount_usd does not match '
                 'any invoice for this plan. Re-read the invoice history. Reply with ONLY: '
                 '{"ticket_id": "<id>", "amount_usd": <number>, "cancel_day": <int>, "cycle_days": <int>}')


SEVERITIES = {
    "P1": ["customer-facing outage, checkout returns HTTP 503 for all users",
           "complete service outage, all API calls failing in two regions"],
    "P2": ["p99 latency degraded from 180ms to 2.4s, error rate 0.8%",
           "elevated error rate 3% on a subset of requests, no full outage"],
    "P3": ["a single replica restarted twice, service healthy overall",
           "one background job retried, users not affected"],
    "P4": ["disk usage at 71% on one node, threshold 70%",
           "certificate expires in 25 days, informational warning"],
}
COMPONENTS = {
    "db": ["postgres primary", "database connection pool", "replication lag on the postgres replica"],
    "network": ["load balancer", "DNS resolution", "TLS handshakes at the ingress"],
    "auth": ["OAuth token service", "login service", "SSO callback handler"],
    "storage": ["object storage bucket", "persistent volume", "S3-compatible blob store"],
}


@dataclass
class Alert:
    alert_id: str
    text: str
    severity: str
    component: str


def make_alert(rng: random.Random, alert_id: str) -> Alert:
    sev = rng.choice(list(SEVERITIES))
    comp = rng.choice(list(COMPONENTS))
    noise = [f"{rng.randint(10, 23)}:{rng.randint(10, 59)}:{rng.randint(10, 59)} INFO heartbeat ok "
             f"shard={rng.randint(1, 64)}" for _ in range(rng.randint(4, 9))]
    text = (f"Alert {alert_id}: {rng.choice(SEVERITIES[sev])}. Suspected component: "
            f"{rng.choice(COMPONENTS[comp])}.\nRecent log lines:\n" + "\n".join(noise))
    return Alert(alert_id, text, sev, comp)


TRIAGE_SYSTEM = (
    "You triage production alerts. Severity: P1 = customer-facing outage; P2 = degraded "
    "performance or partial errors; P3 = minor issue, users not affected; P4 = informational. "
    "Component is one of: db, network, auth, storage. Reply with ONLY JSON: "
    '{"severity": "P1|P2|P3|P4", "component": "db|network|auth|storage"}'
)


def triage_messages(a: Alert) -> list[dict]:
    return [{"role": "system", "content": TRIAGE_SYSTEM}, {"role": "user", "content": a.text}]


PLAYGROUND = ["a haiku about GPUs", "why the sky is blue in two sentences", "a limerick about caching",
              "three tips for writing unit tests", "what a KV cache is, in one paragraph"]


def playground_messages(rng: random.Random) -> list[dict]:
    return [{"role": "user", "content": f"Write {rng.choice(PLAYGROUND)}."}]


_JSON = re.compile(r"\{.*\}", re.S)


def parse_json(text: str) -> dict | None:
    m = _JSON.search(text or "")
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def refund_calculator(amount_usd: float, cancel_day: int, cycle_days: int) -> float:
    """The agent's tool: pro-rated refund of the unused days."""
    return round(amount_usd * (cycle_days - cancel_day) / cycle_days, 2)


def judge_support(t: Ticket, reply: str) -> tuple[bool, float | None]:
    """Gate 1 for support_bot: a well-formed calculator call the tool accepts."""
    v = parse_json(reply)
    if not v:
        return False, None
    try:
        amount, day, cycle = float(v["amount_usd"]), int(v["cancel_day"]), int(v["cycle_days"])
    except (KeyError, TypeError, ValueError):
        return False, None
    if not (0 < amount and 0 <= day < cycle <= 31):
        return False, None
    # The tool validates its arguments against the record: the amount must be
    # an invoice that exists for this plan. (It cannot tell *which* invoice is
    # the most recent one - that is what Gate 2 catches after delivery.)
    if not any(abs(amount - f) < 0.005 for f in t.plan_fees):
        return False, None
    return True, refund_calculator(amount, day, cycle)


def judge_triage(a: Alert, reply: str) -> tuple[bool, dict | None]:
    v = parse_json(reply)
    if not v:
        return False, None
    ok = v.get("severity") in SEVERITIES and v.get("component") in COMPONENTS
    return ok, v


@dataclass
class TaskResult:
    task_id: str
    workload: str
    outcome_id: str
    task_type: str
    start: float
    end: float = 0.0
    attempts: int = 0
    requests: int = 0
    task_quality_bar_met: bool = False
    outcome_quality_bar_met: bool = False
    detail: dict = field(default_factory=dict)
