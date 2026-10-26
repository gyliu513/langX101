#!/usr/bin/env python3
"""Capture the Grafana / Prometheus / Jaeger screenshots for the demo slides.

Runs on the Spark itself (headless Chromium) against the port-forwards from
../scripts/port-forward.sh: Grafana :3000, Prometheus :9091, Jaeger :16686.

One request ties the screenshots together: pick a trace_id from the exemplars
(see README "Choosing the demo request"); the script hovers the exemplar
diamond that carries it on the Grafana panel, then opens the same trace in
Jaeger, so the ids match across slides.

  ~/pwvenv/bin/python scripts/capture-ui.py --trace <id> --from <ms> --to <ms> --out screenshots/
"""
import argparse
import pathlib

from playwright.sync_api import sync_playwright

G, P, J = "http://localhost:3000", "http://localhost:9091", "http://localhost:16686"


def grafana_login(pg):
    pg.goto(f"{G}/login")
    pg.fill("input[name=user]", "admin")
    pg.fill("input[name=password]", "admin")
    pg.click("button[type=submit]")
    pg.wait_for_timeout(1500)
    if pg.locator("text=Skip").count():
        pg.click("text=Skip")


def grafana_panel(pg, a, out):
    pg.goto(f"{G}/d/llm-d-ttft-exemplars/x?orgId=1&viewPanel=panel-1&from={a.frm}&to={a.to}"
            f"&theme=light&kiosk")
    pg.wait_for_timeout(7000)
    pg.screenshot(path=str(out / "grafana-panel-nohover.png"))
    markers = pg.locator('[data-testid="data-testid Exemplar marker"]')
    pts = []
    for i in range(markers.count()):
        bb = markers.nth(i).bounding_box()
        if bb:
            pts.append((bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2))
    print("exemplar markers:", len(pts))
    # Hover by coordinates: an open tooltip covers its neighbours, so move away
    # and dismiss it before each marker. Grafana thins exemplars per query step,
    # so pick the trace_id from the ones it actually draws.
    for cx, cy in sorted(pts, key=lambda q: q[1]):  # highest (slowest) first
        pg.mouse.move(5, 5)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(150)
        pg.mouse.move(cx, cy)
        pg.wait_for_timeout(1300)  # the tooltip shows after ~1s
        if a.trace in pg.locator("body").inner_text():
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(out / "grafana-panel-exemplar.png"))
            print("hovered marker at", int(cx), int(cy))
            return True
    print("trace_id not found on any exemplar marker")
    return False


def prometheus_alert(pg, out):
    pg.goto(f"{P}/alerts?search=LLMDTTFT")
    pg.wait_for_timeout(3000)
    rule = pg.get_by_text("LLMDTTFTP99OverSLO").first
    if rule.count():
        rule.click()
        pg.wait_for_timeout(1000)
    pg.screenshot(path=str(out / "prometheus-alert.png"), full_page=True)


def jaeger_trace(pg, a, out, name):
    pg.goto(f"{J}/trace/{a.trace if name == 'jaeger-trace' else a.before}")
    pg.wait_for_timeout(4000)
    pg.screenshot(path=str(out / f"{name}-tree.png"), full_page=True)
    for span in ("match_block_keys", "scorer.prefix-cach", "llm_request"):
        row = pg.locator(".span-name-wrapper", has_text=span).first
        if row.count():
            row.click()
            pg.wait_for_timeout(700)
    pg.screenshot(path=str(out / f"{name}-expanded.png"), full_page=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="the demo request (after the change)")
    ap.add_argument("--before", help="a trace from before the change, for comparison")
    ap.add_argument("--from", dest="frm", required=True, help="epoch ms")
    ap.add_argument("--to", required=True, help="epoch ms")
    ap.add_argument("--out", default="screenshots")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1600, "height": 820}, device_scale_factor=2,
                            color_scheme="light")
        pg = ctx.new_page()
        grafana_login(pg)
        grafana_panel(pg, a, out)
        prometheus_alert(pg, out)
        jaeger_trace(pg, a, out, "jaeger-trace")
        if a.before:
            jaeger_trace(pg, a, out, "jaeger-before")
        b.close()


if __name__ == "__main__":
    main()
