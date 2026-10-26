#!/usr/bin/env python3
"""Jaeger captures for compose-jaeger.py: the span tree plus the Tags table of
match_block_keys, scorer.prefix-cache-scorer and llm_request (other tags hidden).

Runs on the Spark against the Jaeger port-forward (:16686):
  ~/pwvenv/bin/python scripts/capture-jaeger.py <trace_id> <out dir>
Writes tree.png, detail0..2.png, table0..2.png and rows.json (row positions).
"""
import sys
from playwright.sync_api import sync_playwright
TID,OUTDIR=sys.argv[1],sys.argv[2]
KEEP={"match_block_keys":["llm_d.kv_cache.prefix_match.longest_chain","llm_d.kv_cache.prefix_match.pods_matched","llm_d.kv_cache.prefix_match.key_count"],
      "scorer.prefix-cache-scorer":["llm_d.epp.scorer.weight","llm_d.epp.scorer.score.max","llm_d.epp.scorer.score.avg"],
      "llm_request":["gen_ai.latency.time_in_model_prefill","gen_ai.latency.time_to_first_token","gen_ai.usage.prompt_tokens"]}
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1100,"height":1300},device_scale_factor=2)
    pg.goto(f"http://localhost:16686/trace/{TID}"); pg.wait_for_timeout(3500)
    dr=pg.locator(".VerticalResizer--dragger").first.bounding_box()
    pg.mouse.move(dr["x"]+1, dr["y"]+40); pg.mouse.down(); pg.mouse.move(500, dr["y"]+40, steps=12); pg.mouse.up(); pg.wait_for_timeout(800)
    pg.screenshot(path=f"{OUTDIR}/tree.png")
    import json
    rows={}
    for name in ["match_block_keys","scorer.prefix-cache","llm_request","llm-d-inference-gateway"]:
        bb=pg.locator(".span-row",has_text=name).first.bounding_box(); rows[name]=bb
    hdr=pg.locator("text=Service & Operation").first.bounding_box(); rows["header"]=hdr
    rows["name_col"]=pg.locator(".VerticalResizer--dragger").first.bounding_box()["x"]
    open(f"{OUTDIR}/rows.json","w").write(json.dumps(rows))
    for idx,(name,keys) in enumerate(KEEP.items()):
        pg.locator(".span-row",has_text=name).first.locator(".span-view").first.click(); pg.wait_for_timeout(800)
        d=pg.locator(".detail-info-wrapper").first
        d.locator(".AccordionAttributes--header").first.click(); pg.wait_for_timeout(500)
        pg.evaluate("""(keep)=>{const d=document.querySelector('.detail-info-wrapper');
          d.querySelectorAll('table tr').forEach(tr=>{const k=(tr.innerText||'').split(/\\s/)[0]; if(!keep.includes(k)) tr.style.display='none'});
          d.querySelectorAll('.AccordionAttributes--header').forEach(h=>{if(!h.innerText.includes('Tags')) h.parentElement.style.display='none'});
          d.querySelectorAll('.SpanDetail--debugInfo').forEach(e=>e.style.display='none');}""", keys)
        pg.wait_for_timeout(400)
        d.screenshot(path=f"{OUTDIR}/detail{idx}.png")
        d.locator("table").first.screenshot(path=f"{OUTDIR}/table{idx}.png")
        pg.locator(".span-row",has_text=name).first.locator(".span-view").first.click(); pg.wait_for_timeout(600)
    b.close()
