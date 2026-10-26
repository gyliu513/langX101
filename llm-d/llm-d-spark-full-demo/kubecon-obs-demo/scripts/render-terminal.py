#!/usr/bin/env python3
"""Render captured command output as a terminal-style PNG for the slides.

The text is the real output of the commands (captured to a file first); this
only draws it at a size that stays legible on a projector:

  render-terminal.py --title "kubectl logs ... | jq" --cmd "$ kubectl ..." \
      --in output.txt --out screenshots/s20-logs.png [--diff] [--highlight WORD]

Needs: pip install playwright && playwright install chromium
"""
import argparse
import html
import pathlib

from playwright.sync_api import sync_playwright

CSS = """
body{margin:0;background:transparent;font-family:'JetBrains Mono','SF Mono',Menlo,monospace}
.win{width:%(w)dpx;background:#0f172a;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px #0003}
.bar{height:34px;background:#1e293b;display:flex;align-items:center;padding:0 14px;gap:8px}
.dot{width:12px;height:12px;border-radius:50%%}
.t{color:#94a3b8;font:13px Inter,Helvetica,sans-serif;margin-left:10px}
pre{margin:0;padding:18px 22px;color:#e2e8f0;font-size:%(fs)dpx;line-height:1.45;white-space:pre-wrap;word-break:break-all}
.cmd{color:#7dd3fc}.add{color:#86efac;background:#14532d55}.del{color:#fca5a5;background:#7f1d1d55}
.hunk{color:#c4b5fd}.hl{color:#fde047;font-weight:700}.dim{color:#64748b}
"""


def colorize(line, diff, highlights):
    esc = html.escape(line)
    for h in highlights:
        esc = esc.replace(html.escape(h), f'<span class="hl">{html.escape(h)}</span>')
    if diff:
        if line.startswith("+") and not line.startswith("+++"):
            return f'<span class="add">{esc}</span>'
        if line.startswith("-") and not line.startswith("---"):
            return f'<span class="del">{esc}</span>'
        if line.startswith("@@"):
            return f'<span class="hunk">{esc}</span>'
        if line.startswith(("---", "+++")):
            return f'<span class="dim">{esc}</span>'
    if line.startswith("$ "):
        return f'<span class="cmd">{esc}</span>'
    return esc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="")
    ap.add_argument("--cmd", action="append", default=[])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1400)
    ap.add_argument("--font", type=int, default=19)
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--highlight", action="append", default=[])
    a = ap.parse_args()
    # --cmd lines are shown as a command; a line starting with spaces continues
    # the previous one (no "$ ").
    cmds = [c if c.startswith(" ") else f"$ {c}" for c in a.cmd]
    out = pathlib.Path(a.inp).read_text().rstrip("\n").split("\n")
    body = "\n".join([f'<span class="cmd">{colorize(c, False, a.highlight)}</span>' for c in cmds]
                     + [colorize(l, a.diff, a.highlight) for l in out])
    page_html = (f"<html><head><style>{CSS % {'w': a.width, 'fs': a.font}}</style></head><body>"
                 f"<div class=win><div class=bar><span class=dot style='background:#f87171'></span>"
                 f"<span class=dot style='background:#fbbf24'></span><span class=dot style='background:#4ade80'></span>"
                 f"<span class=t>{html.escape(a.title)}</span></div><pre>{body}</pre></div></body></html>")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(device_scale_factor=2, viewport={"width": a.width + 40, "height": 400})
        pg.set_content(page_html)
        pg.locator(".win").screenshot(path=a.out, omit_background=True)
        b.close()
    print("wrote", a.out)


if __name__ == "__main__":
    main()
