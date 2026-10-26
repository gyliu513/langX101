#!/usr/bin/env python3
"""Hover the highest exemplar diamond right of x=XMIN on the TTFT panel and save
the frame with its tooltip (this is how the slide 17 / 19 image was taken).
  ~/pwvenv/bin/python scripts/hover-top-exemplar.py <from_ms> <to_ms> <xmin_px> <out.png>
"""
import re
import sys

from playwright.sync_api import sync_playwright
F,T,XMIN,OUT=sys.argv[1],sys.argv[2],float(sys.argv[3]),sys.argv[4]
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={"width":1600,"height":820},device_scale_factor=2,color_scheme="light").new_page()
    pg.goto("http://localhost:3000/login"); pg.fill("input[name=user]","admin"); pg.fill("input[name=password]","admin"); pg.click("button[type=submit]"); pg.wait_for_timeout(1500)
    pg.goto(f"http://localhost:3000/d/llm-d-ttft-exemplars/x?orgId=1&viewPanel=panel-1&from={F}&to={T}&theme=light&kiosk"); pg.wait_for_timeout(7000)
    m=pg.locator('[data-testid="data-testid Exemplar marker"]')
    pts=[(bb["y"],bb["x"]+bb["width"]/2,bb["y"]+bb["height"]/2) for bb in (m.nth(i).bounding_box() for i in range(m.count())) if bb and bb["x"]>XMIN]
    pts.sort()
    _,cx,cy=pts[0]
    before=set(re.findall(r"[0-9a-f]{32}",pg.locator("body").inner_text()))
    pg.mouse.move(cx,cy); pg.wait_for_timeout(1500)
    ids=[i for i in re.findall(r"[0-9a-f]{32}",pg.locator("body").inner_text()) if i not in before]
    print("TOP",int(cx),int(cy),ids[:2])
    pg.screenshot(path=OUT)
    b.close()
