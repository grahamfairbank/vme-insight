# Development

## Working on vme-insight

| To change | Edit | Then run |
|---|---|---|
| A dashboard or panel | `tools/build_dashboards.py` (not the JSON) | `python3 tools/build_dashboards.py`, then `python3 tools/check_dashboards.py`: it must report **0 errors** |
| The collector | `collector/vmeinsight/` | `docker compose build collector && docker compose up -d collector`, then watch `docker compose logs -f collector` |
| The database schema | `collector/vmeinsight/schema.sql` (idempotent; applied at every collector start) | Rebuild and restart the collector |
| The https front end | `https/Caddyfile` | `docker compose --profile https up -d https` |
| Documentation screenshots | nothing by hand | `python3 tools/screenshots.py --blur <extra names>`: it blurs server names and IPs and refuses to save if any stay readable. Look at every image before committing. |
| The architecture diagram | `docs/architecture/architecture.html` | Re-render with `docs/architecture/render.py` (command in the file) |

Commit as yourself with the attribution your project uses. Never commit `.env`, `.env.bak*`, `config/config.yaml`, `probe/`, `https/certs/*.crt|*.key` or `installer/dist/`; `.gitignore` excludes them.

## Releases

Versions, the changelog, tags, GitHub releases and the contracts the companion plugin relies on are in [RELEASING](RELEASING.md), the standard shared with [vme-insight-plugin](https://github.com/grahamfairbank/vme-insight-plugin).
