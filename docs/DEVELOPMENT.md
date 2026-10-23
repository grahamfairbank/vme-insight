# Development and releases

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

## Repositories, versions and releases

vme-insight and [vme-insight-plugin](https://github.com/grahamfairbank/vme-insight-plugin) follow the same conventions. The plugin's [DEVELOPMENT](https://github.com/grahamfairbank/vme-insight-plugin/blob/main/docs/DEVELOPMENT.md) describes the same standard from its side.

### Two repositories

| Repository | What it is | Depends on |
|---|---|---|
| [grahamfairbank/vme-insight](https://github.com/grahamfairbank/vme-insight) | This platform: collector, TimescaleDB, Prometheus, Grafana, dashboards. Complete on its own. | VME |
| [grahamfairbank/vme-insight-plugin](https://github.com/grahamfairbank/vme-insight-plugin) | An optional add-on installed in the VME manager that shows these dashboards inside VME. | vme-insight and VME |

They're versioned and released independently: they install into different systems (a Docker host and the VME manager), and many vme-insight users never install the plugin. What ties them together:

* **One setup guide**, here: [VME-PLUGIN](VME-PLUGIN.md). The plugin's docs link to it rather than repeat it.
* **Compatibility tables**, updated with every release of either project: the [README's](../README.md#compatibility) (vme-insight versions) and [VME-PLUGIN's](VME-PLUGIN.md#compatibility) (plugin versions).
* **Contracts** the plugin relies on, which vme-insight keeps stable: dashboard uids and variables (`vme-hosts`/`var-host`, `vme-vms`/`var-vm`, `vme-overview`/`var-cluster`) and the `vme-widget` dashboard's panel ids, which are never renumbered or reused. Also the https front end settings the plugin's setup uses (`HTTPS_*`, `GRAFANA_ANONYMOUS`, `GRAFANA_ALLOW_EMBEDDING`, `GRAFANA_ROOT_URL`). Changing any of these is a breaking change for the plugin and needs a compatibility row saying so.

### Versions

`MAJOR.MINOR.PATCH`. While the major version is 0: a new feature or setting bumps MINOR; fixes and documentation-only releases bump PATCH. The version lives in `collector/vmeinsight/__init__.py` (`__version__`).

### Changelog

`CHANGELOG.md`, newest first. Each release has a heading `## <version> (<YYYY-MM-DD>)`, with bullets for what changed from a user's point of view. While work collects before a release, the heading reads `## <version> (unreleased)`. Note anything an upgrading user must do: a rebuild, a new `.env` setting, a changed mount.

### Releasing

1. **Release commit.** Set `__version__`, date the changelog heading, and add a row to the README's **Compatibility** table. Commit as `Release <version>: <summary>`.
2. **Checks.** `docker compose build` succeeds, the collector starts and collects (`docker compose logs collector` shows each task's item count), and `python3 tools/check_dashboards.py` reports **0 errors**. If the release changes what dashboards look like, refresh the screenshots and look at every one before committing.
3. **Annotated tag** on the release commit, named `v<version>`, with a one-line summary:
   ```bash
   git tag -a v0.4.5 -m "vme-insight 0.4.5: <summary>"
   git push origin main v0.4.5
   ```
4. **GitHub release** for the tag, titled `vme-insight v<version>`, with notes saying what changed, what an upgrading user must do, the upgrade command, and the community-project disclaimer. There's no artifact: users install from the source. This needs a GitHub login (for example `gh release create v0.4.5 --title "vme-insight v0.4.5" --notes-file release-notes.md`). A deploy key can push the tag but not create the release.
5. **The plugin's compatibility table.** If the release changes a contract above, or the plugin needs it, update the rows in VME-PLUGIN and in the plugin's README in the same week.

Upgrading users run:

```bash
cd ~/vme-insight
git pull
docker compose build
docker compose up -d
```

and add `--profile https` (and `--profile installer`) to the last command if they use those services.
