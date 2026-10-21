"""Render architecture.html to a one-page PDF and a PNG preview.

Run from docs/architecture with the screenshot tool's browser image (built by tools/screenshots.py):
  docker run --rm --shm-size=1g --user $(id -u) -e HOME=/tmp -v $PWD:/work -v /tmp:/out \
    vme-insight-shots python /work/render.py
"""
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1056, "height": 816}, locale="en-US")
    p.goto("file:///work/architecture.html")
    p.wait_for_selector("body[data-ready]")
    p.pdf(path="/work/vme-insight-architecture.pdf", width="11in", height="8.5in", print_background=True,
          margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}, page_ranges="1")
    p.screenshot(path="/out/preview.png", full_page=False)
    b.close()
print("rendered")
