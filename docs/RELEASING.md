# Repositories, versions and releases

vme-insight and its companion VME plugin follow the same conventions. This page is for maintainers; users only need the [Releases](https://github.com/grahamfairbank/vme-insight/releases) page and the README's [Compatibility](../README.md#compatibility) table.

## Two repositories

| Repository | What it is | Depends on |
|---|---|---|
| [grahamfairbank/vme-insight](https://github.com/grahamfairbank/vme-insight) | The platform: collector, TimescaleDB, Prometheus, Grafana, dashboards. Complete on its own. | VME |
| [grahamfairbank/vme-insight-plugin](https://github.com/grahamfairbank/vme-insight-plugin) | An optional add-on installed in the VME manager, showing these dashboards inside VME. | vme-insight and VME |

They're versioned and released independently: they install into different systems (a Docker host and the VME manager), and many vme-insight users never install the plugin. What ties them together:

* **One setup guide**, here: [VME-PLUGIN](VME-PLUGIN.md). The plugin's docs link to it rather than repeat it.
* **Compatibility tables** in both READMEs, updated with every release of either project.
* **Contracts** the plugin relies on, which vme-insight keeps stable:
  * dashboard uids and variables: `vme-hosts`/`var-host`, `vme-vms`/`var-vm`, `vme-overview`/`var-cluster`;
  * the `vme-widget` panel ids ([DASHBOARDS](DASHBOARDS.md#vme-summary-tiles-for-embedding)), which are never renumbered or reused;
  * the https front end and anonymous-viewing settings described in VME-PLUGIN.

  Changing any of these breaks the plugin. Avoid it; if it can't be avoided, release a matching plugin version and say so in both compatibility tables.

## Versions

`MAJOR.MINOR.PATCH`. While the major version is 0: a new feature, dashboard or setting bumps MINOR; fixes and documentation-only releases bump PATCH. The version lives in `collector/vmeinsight/__init__.py` (`__version__`).

## Changelog

`CHANGELOG.md`, newest first. Each release has a heading `## <version> (<YYYY-MM-DD>)`, with bullets for what changed from a user's point of view. Call out anything that needs action on upgrade: a new or renamed setting, a rebuild, a database change, a newer VME.

## Releasing

1. **Release commit.** Set `__version__`, date the changelog heading, and add a row to the README's **Compatibility** table. Commit as `Release <version>: <summary>`.
2. **Check.** `python3 tools/build_dashboards.py` leaves no diff, `python3 tools/check_dashboards.py` reports no errors, and the stack starts cleanly after `docker compose build` and `docker compose up -d`.
3. **Annotated tag** on the release commit, named `v<version>`, with a one-line summary, then push both:
   ```bash
   git tag -a v0.4.5 -m "vme-insight 0.4.5: <summary>"
   git push origin main v0.4.5
   ```
4. **GitHub release** for the tag, titled `vme-insight v<version>`. The notes say what changed, how to upgrade (usually `git pull`, `docker compose build`, `docker compose up -d`, as in [INSTALL](INSTALL.md#upgrading)), compatibility (VME and the optional plugin), and the community-project disclaimer:
   ```bash
   gh release create v0.4.5 --title "vme-insight v0.4.5" --notes-file release-notes.md
   ```
5. **Plugin compatibility.** If the release changes anything in the contracts above, release a plugin version that works with it and update both compatibility tables.

The plugin releases the same way, with its jar and SHA-256 attached to each GitHub release; see its [DEVELOPMENT](https://github.com/grahamfairbank/vme-insight-plugin/blob/main/docs/DEVELOPMENT.md#repositories-versions-and-releases).
