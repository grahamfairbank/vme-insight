"""Map the OS strings Morpheus reports to endoflife.date product/cycle ids."""
import re

# (product, regex on the combined OS text, cycle style)
# cycle styles: major -> "9"; yy.mm -> "22.04"; sp -> "15.5" from "15 SP5"; winsrv -> "2019"/"2012-r2"
RULES = [
    ("ubuntu", r"ubuntu", "yy.mm"),
    ("rhel", r"red\s*hat|\brhel\b", "major"),
    ("rocky-linux", r"rocky", "major"),
    ("almalinux", r"alma", "major"),
    ("centos-stream", r"centos\s*stream", "major"),
    ("centos", r"centos", "major"),
    ("oracle-linux", r"oracle", "major"),
    ("debian", r"debian", "major"),
    ("sles", r"\bsles\b|suse\s+linux\s+enterprise", "sp"),
    ("opensuse", r"opensuse", "x.y"),
    ("fedora", r"fedora", "major"),
    ("amazon-linux", r"amazon", "major"),
    ("windows-server", r"windows.*server|server.*windows", "winsrv"),
    ("windows", r"windows", "major"),
    ("freebsd", r"freebsd", "x.y"),
]


def _cycle(style, text, version):
    src = f"{version or ''} {text}"
    if style == "yy.mm":
        m = re.search(r"(\d{2}\.\d{2})", src)
        return m.group(1) if m else None
    if style == "sp":
        m = re.search(r"(\d{2})\s*sp\s*(\d)", src, re.I) or re.search(r"(\d{2})\.(\d)", src)
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        m = re.search(r"\b(\d{2})\b", src)
        return m.group(1) if m else None
    if style == "winsrv":
        m = re.search(r"(20\d\d)(\s*r2)?", text, re.I)
        if not m:
            return None
        return m.group(1) + ("-r2" if m.group(2) else "")
    if style == "x.y":
        m = re.search(r"(\d+\.\d+)", src)
        return m.group(1) if m else None
    m = re.search(r"(\d+)", src)
    return m.group(1) if m else None


# A Linux kernel release rather than an OS version: "5.14.0-427.13.1.el9_4.x86_64", "6.8.0-45-generic"
KERNEL_RELEASE = re.compile(r"^\d+\.\d+\.\d+-|x86_64|aarch64|\.el\d|\.fc\d|-generic|-amd64")


def detect(server, extra_rules=()):
    """Return (product, cycle, full_version) or (None, None, None)."""
    os_ = server.get("serverOs") or {}
    parts = [os_.get("name"), os_.get("vendor"), os_.get("version"),
             server.get("platform"), server.get("osType")]
    text = " ".join(str(p) for p in parts if p).lower()
    pv = str(server.get("platformVersion") or os_.get("version") or "")
    if KERNEL_RELEASE.search(pv):
        # VME reports the kernel release for some guests (e.g. Rocky, RHEL):
        # "6.12.0-211.16.1.el10_2.0.1.x86_64". Its "elN_M" marker is the OS version;
        # otherwise the kernel numbers say nothing about the OS release.
        el = re.search(r"\.el(\d+)(?:_(\d+))?", pv)
        full = (f"{el.group(1)}.{el.group(2)}" if el.group(2) else el.group(1)) if el else None
    else:
        m = re.search(r"\d+(?:\.\d+)+|\d+", pv)
        full = m.group(0) if m else None
    if not full:
        m = re.search(r"\d+\.\d+(?:\.\d+)*", text)
        full = m.group(0) if m else None

    for rule in extra_rules or ():
        if re.search(rule["match"], text, re.I):
            cyc = None
            if rule.get("cycle"):
                cm = re.search(rule["cycle"], f"{full or ''} {text}", re.I)
                cyc = cm.group(1) if cm else None
            return rule["product"], cyc, full
    for product, rx, style in RULES:
        if re.search(rx, text):
            return product, _cycle(style, text, full), full
    return None, None, full
