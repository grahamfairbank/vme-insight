#!/usr/bin/env python3
"""Make or check grafana/theme/index.html: Grafana's page template plus the vme-insight stylesheet.

    python3 tools/grafana_index.py          write grafana/theme/index.html from the Grafana image
    python3 tools/grafana_index.py --check  exit 1 if it no longer matches the image in docker-compose.yml

The template comes from the exact Grafana image docker-compose.yml runs, with one <link> line added
before </head>. Run it again (and commit the result) whenever the Grafana image changes.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "grafana" / "theme" / "index.html"
LINK = ('    <!-- vme-insight: HPE backgrounds (grafana/theme/hpe.css); this file is made by tools/grafana_index.py -->\n'
        '    <link rel="stylesheet" href="public/vme-insight/hpe.css" />\n')


def grafana_image():
    m = re.search(r"image:\s*(grafana/grafana:\S+)", (ROOT / "docker-compose.yml").read_text())
    if not m:
        sys.exit("no grafana/grafana image in docker-compose.yml")
    return m.group(1)


def upstream(image):
    return subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", image,
                           "/usr/share/grafana/public/views/index.html"],
                          check=True, capture_output=True, text=True).stdout


def themed(html):
    if html.count("  </head>") != 1:
        sys.exit("Grafana's index.html has no single </head>; update tools/grafana_index.py")
    return html.replace("  </head>", LINK + "  </head>", 1)


def main():
    image = grafana_image()
    want = themed(upstream(image))
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != want:
            sys.exit(f"grafana/theme/index.html does not match {image}: run python3 tools/grafana_index.py")
        print(f"grafana/theme/index.html matches {image}")
        return
    OUT.write_text(want)
    print(f"wrote grafana/theme/index.html from {image}")


if __name__ == "__main__":
    main()
