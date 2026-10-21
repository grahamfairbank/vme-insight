"""Capture vme-insight dashboards as PNGs, blurring sensitive names first.

Runs inside the vme-insight-shots container (see tools/screenshots.py, which starts it).
Text is blurred in the page before capture, so screenshots show real data with
server names and addresses unreadable. Nothing is altered or invented.
"""
import json
import os
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("GRAFANA_URL", "http://grafana:3000")
USER, PASSWORD = os.environ["GF_USER"], os.environ["GF_PASSWORD"]
TERMS = json.loads(os.environ.get("BLUR_TERMS", "[]"))
PATTERNS = json.loads(os.environ.get("BLUR_PATTERNS", "[]"))
T_FROM, T_TO = os.environ["T_FROM"], os.environ["T_TO"]
OUT = os.environ.get("OUT", "/out")
WIDTH = int(os.environ.get("WIDTH", "1600"))

# (file name, dashboard uid, extra URL params)
FULL = [
    ("overview", "vme-overview", ""),
    ("hosts", "vme-hosts", ""),
    ("vms", "vme-vms", ""),
    ("lifecycle", "vme-lifecycle", "&from=now-7d&to=now"),
    ("manager", "vme-health", ""),
    ("hvm-hosts", "vme-hvm-hosts", ""),
    ("hvm-bottlenecks", "vme-hvm-bottlenecks", ""),
    ("hvm-capacity", "vme-hvm-capacity", ""),
    ("export", "vme-export", ""),
]
# (file name, dashboard uid, panel titles whose combined area is cropped)
CROPS = [
    ("hero", "vme-overview", ["Clusters", "Cluster memory usage (add hosts above 70%)"]),
    ("cpu-contention", "vme-overview", ["Worst VM CPU ready", "VMs over 10% ready"]),
    ("n-plus-1", "vme-overview", ["N+1 failover headroom: VM memory vs capacity left if a host fails"]),
    ("datastores", "vme-overview", ["Datastore usage (amber 80%, red 90%)", "Datastores"]),
    ("lifecycle-table", "vme-lifecycle", ["Servers tracked", "OS and agent currency"]),
    ("manager-resources", "vme-health", ["Disk used (amber 75%, red 85%)", "Manager disk used % (amber 75, red 85)"]),
    ("host-filesystems", "vme-hvm-hosts", ["Host filesystems (node_exporter)", "Filesystem free space"]),
    ("bottlenecks-cpu", "vme-hvm-bottlenecks", ["CPU pressure (PSI some)", "vCPU wait % now (healthy < 5%)"]),
    ("capacity-table", "vme-hvm-capacity", ["Capacity per host", "Memory allocated / host memory"]),
]

# (file name, dashboard uid, panel title): the panel with its guidance tooltip open
TOOLTIPS = [
    ("tip-cpu-ready", "vme-hosts", "CPU ready (healthy < 5%, act > 10%)"),
    ("tip-memory-alarm", "vme-hosts", "Memory usage"),
    ("tip-n-plus-1", "vme-hosts", "N+1 failover capacity per cluster"),
    ("tip-manager-disk", "vme-health", "Disk used (amber 75%, red 85%)"),
    ("tip-manager-size", "vme-health", "Manager size vs HPE recommendation"),
    ("tip-vcpu-wait", "vme-hvm-bottlenecks", "Top 10 VMs by vCPU wait % (healthy < 5%, act > 10%)"),
    ("tip-host-filesystems", "vme-hvm-hosts", "Host filesystems (node_exporter)"),
]

HOVER_JS = """
(title) => {
  const h = [...document.querySelectorAll('h2')].filter(e => (e.textContent || '').trim() === title).pop();
  if (!h) return null;
  const item = h.closest('.react-grid-item');
  const icon = h.closest('[data-testid="header-container"]').querySelector('[data-testid="title-items-container"] span');
  item.scrollIntoView({block: 'center'});
  return icon ? true : null;
}
"""

TOOLTIP_RECT_JS = """
(title) => {
  const h = [...document.querySelectorAll('h2')].filter(e => (e.textContent || '').trim() === title).pop();
  const rects = [h.closest('.react-grid-item').getBoundingClientRect()];
  document.querySelectorAll('[role="tooltip"]').forEach(t => { const r = t.getBoundingClientRect(); if (r.width > 0) rects.push(r); });
  return {n: rects.length - 1, x0: Math.min(...rects.map(r => r.left)), y0: Math.min(...rects.map(r => r.top)),
          x1: Math.max(...rects.map(r => r.right)), y1: Math.max(...rects.map(r => r.bottom))};
}
"""

BLUR_JS = """
([terms, patterns]) => {
  const esc = s => s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
  // whole words only, so a VM called "test" doesn't blur "latest"
  const parts = terms.filter(Boolean).map(t => '(?<![\\\\w])' + esc(t) + '(?![\\\\w])').concat(patterns);
  if (!parts.length) return 0;
  const rx = new RegExp(parts.join('|'), 'i');
  const hits = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.parentElement && rx.test(node.nodeValue)) hits.add(node.parentElement);
  }
  // text inside inputs (e.g. a variable picker showing a host)
  document.querySelectorAll('input').forEach(i => { if (rx.test(i.value || '')) hits.add(i); });
  hits.forEach(el => { el.style.filter = 'blur(6px)'; });
  return hits.size;
}
"""

LEAK_JS = """
([terms, patterns]) => {
  const esc = s => s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
  const rx = new RegExp(terms.filter(Boolean).map(t => '(?<![\\\\w])' + esc(t) + '(?![\\\\w])').concat(patterns).join('|'), 'i');
  const leaks = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode, el = n.parentElement;
    if (!el || !rx.test(n.nodeValue)) continue;
    let blurred = false;
    for (let e = el; e; e = e.parentElement) if ((e.style.filter || '').includes('blur')) { blurred = true; break; }
    const r = el.getBoundingClientRect();
    if (!blurred && r.width > 0 && r.height > 0) leaks.push(n.nodeValue.trim().slice(0, 60));
  }
  return leaks;
}
"""

PANEL_RECTS_JS = """
(titles) => {
  const rects = [];
  for (const t of titles) {
    // last match: a title can also appear earlier as a stat tile (e.g. "Datastores")
    const h = [...document.querySelectorAll('h2, h6, [title]')].filter(e => (e.textContent || '').trim() === t).pop();
    if (!h) continue;
    const item = h.closest('.react-grid-item');
    if (item) rects.push(item.getBoundingClientRect().toJSON());
  }
  return rects;
}
"""


def settle(page):
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    page.wait_for_load_state("networkidle")
    page.mouse.move(0, 0)  # no hover tooltips
    time.sleep(1)


def open_dashboard(page, uid, extra):
    rng = extra or f"&from={T_FROM}&to={T_TO}"
    page.set_viewport_size({"width": WIDTH, "height": 6000})  # tall, so lazy panels all load
    page.goto(f"{BASE}/d/{uid}?orgId=1&kiosk&theme=dark{rng}", wait_until="domcontentloaded")
    settle(page)
    n = page.evaluate(BLUR_JS, [TERMS, PATTERNS])
    leaks = page.evaluate(LEAK_JS, [TERMS, PATTERNS])
    if leaks:
        raise SystemExit(f"{uid}: unblurred sensitive text found, not saving: {leaks}")
    bottom = page.evaluate("Math.max(...[...document.querySelectorAll('.react-grid-item')]"
                           ".map(e => e.getBoundingClientRect().bottom), 400)")
    return n, int(bottom) + 16


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # an explicit locale is required: Grafana fails to start with the container's empty one
        ctx = browser.new_context(viewport={"width": WIDTH, "height": 6000}, device_scale_factor=1,
                                  color_scheme="dark", locale="en-US", timezone_id=os.environ.get("TZ", "UTC"))
        r = ctx.request.post(f"{BASE}/login", data={"user": USER, "password": PASSWORD})
        if not r.ok:
            raise SystemExit(f"Grafana login failed: HTTP {r.status}")
        page = ctx.new_page()

        for name, uid, extra in FULL:
            n, height = open_dashboard(page, uid, extra)
            path = f"{OUT}/{name}.png"
            page.screenshot(path=path, clip={"x": 0, "y": 0, "width": WIDTH, "height": height})
            print(f"{path}: {height}px tall, {n} elements blurred")

        for name, uid, titles in CROPS:
            extra = next(e for f, u, e in FULL if u == uid)
            n, _ = open_dashboard(page, uid, extra)
            rects = page.evaluate(PANEL_RECTS_JS, titles)
            if len(rects) != len(titles):
                raise SystemExit(f"{name}: found {len(rects)} of {len(titles)} panels {titles}")
            x0 = max(min(r["left"] for r in rects) - 8, 0)
            y0 = max(min(r["top"] for r in rects) - 8, 0)
            x1 = min(max(r["right"] for r in rects) + 8, WIDTH)
            y1 = max(r["bottom"] for r in rects) + 8
            path = f"{OUT}/{name}.png"
            page.screenshot(path=path, clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
            print(f"{path}: {int(x1 - x0)}x{int(y1 - y0)}, {n} elements blurred")

        for name, uid, title in TOOLTIPS:
            extra = next(e for f, u, e in FULL if u == uid)
            open_dashboard(page, uid, extra)
            if not page.evaluate(HOVER_JS, title):
                raise SystemExit(f"{name}: panel or info icon not found for {title!r}")
            h2 = page.locator("h2", has_text=title).last
            h2.locator("xpath=ancestor::*[@data-testid='header-container']//*[@data-testid='title-items-container']//span").first.hover()
            time.sleep(1.2)
            page.evaluate(BLUR_JS, [TERMS, PATTERNS])
            leaks = page.evaluate(LEAK_JS, [TERMS, PATTERNS])
            if leaks:
                raise SystemExit(f"{name}: unblurred sensitive text found, not saving: {leaks}")
            r = page.evaluate(TOOLTIP_RECT_JS, title)
            if not r["n"]:
                raise SystemExit(f"{name}: tooltip did not open")
            x0, y0 = max(r["x0"] - 10, 0), max(r["y0"] - 10, 0)
            clip = {"x": x0, "y": y0, "width": min(r["x1"] + 10, WIDTH) - x0, "height": r["y1"] + 10 - y0}
            path = f"{OUT}/{name}.png"
            page.screenshot(path=path, clip=clip)
            page.mouse.move(0, 0)
            print(f"{path}: {int(clip['width'])}x{int(clip['height'])}, tooltip open")
        browser.close()


if __name__ == "__main__":
    main()
