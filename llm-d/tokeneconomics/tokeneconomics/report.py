"""Render the KPI views as Markdown (for the README) and HTML (for screenshots).

    python3 -m tokeneconomics.report --data data
"""

from __future__ import annotations

import argparse
import html
import os
import sqlite3


def q(db, sql, *a):
    db.row_factory = sqlite3.Row
    return [dict(r) for r in db.execute(sql, a)]


def money(x, digits=4):
    return "-" if x is None else f"${x:,.{digits}f}"


def pct(x):
    return "-" if x is None else f"{100 * x:.1f}%"


def num(x, digits=0):
    return "-" if x is None else f"{x:,.{digits}f}"


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def build(db):
    phases = [r["phase"] for r in q(db, "SELECT phase FROM phase ORDER BY start")]
    notes = {r["phase"]: r["note"] for r in q(db, "SELECT phase, note FROM phase")}
    infra = q(db, "SELECT * FROM kpi_infra ORDER BY phase, WorkloadId")
    wl = q(db, "SELECT * FROM kpi_workload ORDER BY phase, WorkloadId")
    ph = {r["phase"]: r for r in q(db, "SELECT * FROM kpi_phase")}
    counts = {t: q(db, f"SELECT COUNT(*) n FROM {t}")[0]["n"]
              for t in ("cost_and_usage", "telemetry", "task", "outcome", "value")}
    return phases, notes, infra, wl, ph, counts


def markdown(phases, notes, infra, wl, ph, counts) -> str:
    s = ["# Token-economics KPIs", ""]
    s.append("Datasets: " + ", ".join(f"`{k}` {v} rows" for k, v in counts.items()))
    s.append("")
    s.append("## Phases")
    s.append(md_table(["phase", "note"], [[p, notes.get(p, "")] for p in phases]))
    s.append("\n## 4.1 Infrastructure (per phase and workload)")
    s.append(md_table(["phase", "workload", "requests", "input tok", "output tok", "KV cache hit", "prefill GPU-s",
                       "decode GPU-s", "allocated cost", "cost / 1M tok"],
                      [[r["phase"], r["WorkloadId"], num(r["requests"]), num(r["input_tokens"]),
                        num(r["output_tokens"]), pct(r["kv_cache_hit_ratio"]), num(r["prefill_gpu_s"], 1),
                        num(r["decode_gpu_s"], 1), money(r["cost_usd"]), money(r["cost_per_1m_tokens"], 3)]
                       for r in infra if r["phase"] in phases]))
    s.append("\n## 4.2-4.4 Yield, outcomes and cost to value (per phase and workload)")
    s.append(md_table(["phase", "workload", "tasks", "task yield", "CPQT", "outcomes", "SLA survival", "CPQO",
                       "GPU-s / QO", "net outcome", "est. value", "spend / $1 value"],
                      [[r["phase"], r["WorkloadId"], num(r["tasks"]), pct(r["task_yield"]), money(r["cpqt"], 5),
                        num(r["outcomes"]), pct(r["sla_survival"]), money(r["cpqo"], 5), num(r["gpu_s_per_qo"], 3),
                        f'{num(r["net_outcome"], 1)} {r["unit"]}', money(r["estimated"], 2),
                        ("n/a (value <= 0)" if r["spend_to_value"] is None else money(r["spend_to_value"], 6))] for r in wl]))
    s.append("\n## Portfolio (per phase)")
    s.append(md_table(["phase", "total cost", "IDLE", "UNLINKED", "failed-task cost", "scrap rate",
                       "of which UNLINKED", "qualified outcomes"],
                      [[p, money(ph[p]["total_cost"]), money(ph[p]["idle_cost"]), money(ph[p]["unlinked_cost"]),
                        money(ph[p]["failed_cost"]), pct(ph[p]["scrap_rate"]), pct(ph[p]["scrap_unlinked_share"]),
                        num(ph[p]["q_outcomes"])] for p in phases if p in ph]))
    return "\n".join(s) + "\n"


CSS = """
:root{--bg:#fff;--fg:#1d2433;--muted:#5b6475;--line:#e3e6ec;--a:#2f6fd6;--b:#d9822b;--good:#1f8a5b;--bad:#c2412d}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px} .muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin-top:16px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card h3{margin:0 0 6px;font-size:13px;color:var(--muted);font-weight:600}
.bar{display:flex;align-items:center;gap:8px;margin:4px 0;font-variant-numeric:tabular-nums}
.bar span.l{width:70px;color:var(--muted);font-size:12px} .bar div{height:14px;border-radius:3px}
.bar b{font-weight:600;font-size:13px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:12.5px}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:right} th:first-child,td:first-child,
th:nth-child(2),td:nth-child(2){text-align:left} th{color:var(--muted);font-weight:600}
.delta{font-size:12px;margin-left:4px} .up{color:var(--bad)} .down{color:var(--good)}
"""


def html_page(phases, notes, infra, wl, ph, counts) -> str:
    colors = ["var(--a)", "var(--b)", "#7a5af8", "#0e9384"]
    e = html.escape

    def bars(title, getter, fmt, lower_is_better=True):
        vals = [(p, getter(p)) for p in phases]
        vmax = max([v for _, v in vals if v is not None] or [1]) or 1
        rows = []
        for i, (p, v) in enumerate(vals):
            w = 0 if v is None else 260 * v / vmax
            delta = ""
            if i > 0 and v is not None and vals[0][1]:
                d = v / vals[0][1] - 1
                cls = ("up" if d > 0 else "down") if lower_is_better else ("down" if d > 0 else "up")
                delta = f'<span class="delta {cls}">{d:+.0%}</span>'
            rows.append(f'<div class="bar"><span class="l">{e(p)}</span><div style="width:{w:.0f}px;'
                        f'background:{colors[i % 4]}"></div><b>{fmt(v)}</b>{delta}</div>')
        return f'<div class="card"><h3>{e(title)}</h3>{"".join(rows)}</div>'

    def wv(p, wlid, key):
        return next((r[key] for r in wl if r["phase"] == p and r["WorkloadId"] == wlid), None)

    def iv(p, wlid, key):
        return next((r[key] for r in infra if r["phase"] == p and r["WorkloadId"] == wlid), None)

    cards = [
        bars("support_bot - KV cache hit ratio", lambda p: iv(p, "support_bot", "kv_cache_hit_ratio"), pct, False),
        bars("support_bot - prefill GPU-seconds", lambda p: iv(p, "support_bot", "prefill_gpu_s"),
             lambda v: num(v, 1)),
        bars("support_bot - GPU-s per qualified outcome", lambda p: wv(p, "support_bot", "gpu_s_per_qo"),
             lambda v: num(v, 3)),
        bars("support_bot - CPQO (allocated)", lambda p: wv(p, "support_bot", "cpqo"), lambda v: money(v, 5)),
        bars("Cost per 1M tokens - support_bot", lambda p: iv(p, "support_bot", "cost_per_1m_tokens"),
             lambda v: money(v, 3)),
        bars("Cost per 1M tokens - triage_bot", lambda p: iv(p, "triage_bot", "cost_per_1m_tokens"),
             lambda v: money(v, 3)),
        bars("CPQO - triage_bot", lambda p: wv(p, "triage_bot", "cpqo"), lambda v: money(v, 5)),
        bars("Scrap rate (UNLINKED + failed tasks)", lambda p: ph.get(p, {}).get("scrap_rate"), pct),
    ]

    def table(headers, rows):
        return ("<table><tr>" + "".join(f"<th>{e(h)}</th>" for h in headers) + "</tr>" +
                "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</table>")

    wl_rows = [[r["phase"], r["WorkloadId"], num(r["tasks"]), pct(r["task_yield"]), money(r["cpqt"], 5),
                pct(r["sla_survival"]), money(r["cpqo"], 5), num(r["gpu_s_per_qo"], 3),
                f'{num(r["net_outcome"], 1)} {r["unit"]}', money(r["estimated"], 2)] for r in wl]
    ph_rows = [[p, "", money(ph[p]["total_cost"]), money(ph[p]["idle_cost"]), money(ph[p]["unlinked_cost"]),
                money(ph[p]["failed_cost"]), pct(ph[p]["scrap_rate"]), pct(ph[p]["scrap_unlinked_share"])]
               for p in phases if p in ph]
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>llm-d Token Economics</title><style>{CSS}</style></head><body><main>
<h1>llm-d token economics: cost per token &rarr; cost per qualified outcome</h1>
<div class="muted">Five datasets ({", ".join(f"{k}: {v}" for k, v in counts.items())}).
Phases: {"; ".join(f"<b>{e(p)}</b> {e(notes.get(p, ''))}" for p in phases)}. Prices illustrative.</div>
<div class="cards">{"".join(cards)}</div>
<h2>Yield, outcomes and value (per phase, workload)</h2>
{table(["phase", "workload", "tasks", "task yield", "CPQT", "SLA survival", "CPQO", "GPU-s / QO", "net outcome", "est. value"], wl_rows)}
<h2>Portfolio</h2>
{table(["phase", "", "total cost", "IDLE", "UNLINKED", "failed-task cost", "scrap rate", "of which UNLINKED"], ph_rows)}
</main></body></html>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data")
    args = p.parse_args()
    db = sqlite3.connect(os.path.join(args.data, "tokeneconomics.db"))
    parts = build(db)
    md = markdown(*parts)
    with open(os.path.join(args.data, "report.md"), "w") as f:
        f.write(md)
    with open(os.path.join(args.data, "report.html"), "w") as f:
        f.write(html_page(*parts))
    print(md)


if __name__ == "__main__":
    main()
