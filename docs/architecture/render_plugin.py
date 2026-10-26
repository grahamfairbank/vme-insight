"""Render plugin.html to PNG (for the docs) and PDF. Run like render.py, in the vme-insight-shots image:
  docker run --rm --shm-size=1g --user $(id -u) -e HOME=/tmp -v $PWD:/work vme-insight-shots python /work/render_plugin.py
"""
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1600, "height": 1210}, device_scale_factor=1.5, locale="en-US")
    p.goto("file:///work/plugin.html")
    p.wait_for_selector("body[data-ready]")
    p.screenshot(path="/work/vme-insight-plugin.png", full_page=False)
    p.pdf(path="/work/vme-insight-plugin.pdf", width="1600px", height="1210px", print_background=True,
          margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}, page_ranges="1")
    b.close()
print("rendered")
