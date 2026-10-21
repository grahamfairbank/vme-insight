"""OS end-of-life data from endoflife.date (https://endoflife.date)."""
import logging

import requests

log = logging.getLogger(__name__)

DEFAULT_PRODUCTS = ["ubuntu", "rhel", "rocky-linux", "almalinux", "debian", "windows-server"]


def _date(v):
    return v if isinstance(v, str) and len(v) == 10 and v[4] == "-" else None


def fetch(api, product, timeout=20):
    """Return a list of normalised release-cycle dicts for one product."""
    base = api.rstrip("/")
    r = requests.get(f"{base}/api/v1/products/{product}", timeout=timeout,
                     headers={"User-Agent": "vme-insight", "Accept": "application/json"})
    if r.status_code == 200:
        out = []
        for rel in (r.json().get("result") or {}).get("releases") or []:
            latest = rel.get("latest") or {}
            out.append(dict(
                cycle=str(rel.get("name")), release_date=_date(rel.get("releaseDate")),
                eol_date=_date(rel.get("eolFrom")), eol_bool=rel.get("isEol"),
                support_date=_date(rel.get("eoasFrom")), lts=rel.get("isLts"),
                latest=latest.get("name"), latest_date=_date(latest.get("date"))))
        return out
    # legacy API
    r = requests.get(f"{base}/api/{product}.json", timeout=timeout, headers={"User-Agent": "vme-insight"})
    if r.status_code != 200:
        log.warning("endoflife.date: no data for %s (HTTP %s)", product, r.status_code)
        return []
    out = []
    for c in r.json():
        eol = c.get("eol")
        out.append(dict(
            cycle=str(c.get("cycle")), release_date=_date(c.get("releaseDate")),
            eol_date=_date(eol), eol_bool=eol if isinstance(eol, bool) else None,
            support_date=_date(c.get("support")), lts=bool(c.get("lts")),
            latest=c.get("latest"), latest_date=_date(c.get("latestReleaseDate"))))
    return out


def refresh(db, cfg):
    lc = cfg["lifecycle"]
    db.set_setting("expected_agent_version", lc.get("expected_agent_version") or "")
    if not lc.get("enabled", True):
        return 0
    seen = {p for (p,) in db.execute(
        "SELECT DISTINCT os_product FROM servers WHERE present AND os_product IS NOT NULL") or []}
    products = sorted(seen | set(DEFAULT_PRODUCTS) | set(lc.get("extra_products") or []))
    n = 0
    for p in products:
        try:
            cycles = fetch(lc["api"], p)
        except requests.RequestException as e:
            log.warning("endoflife.date %s: %s", p, e)
            continue
        for c in cycles:
            db.execute(
                """INSERT INTO os_lifecycle (product, cycle, release_date, eol_date, eol_bool, support_date,
                                             lts, latest, latest_date, fetched_at)
                   VALUES (%(p)s, %(cycle)s, %(release_date)s, %(eol_date)s, %(eol_bool)s, %(support_date)s,
                           %(lts)s, %(latest)s, %(latest_date)s, now())
                   ON CONFLICT (product, cycle) DO UPDATE SET release_date = EXCLUDED.release_date,
                     eol_date = EXCLUDED.eol_date, eol_bool = EXCLUDED.eol_bool,
                     support_date = EXCLUDED.support_date, lts = EXCLUDED.lts, latest = EXCLUDED.latest,
                     latest_date = EXCLUDED.latest_date, fetched_at = now()""",
                dict(c, p=p))
            n += 1
    log.info("lifecycle: %d release cycles across %d products", n, len(products))
    return n
