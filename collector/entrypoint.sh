#!/bin/sh
# Start as root only to read the mounted config, whoever owns it on the host and whatever its
# mode (e.g. root-owned 600), then run the collector as an unprivileged user.
#
#   /config-src  host's ./config, mounted read-only
#   /config      private copy for the collector (mode 600), so paths like /config/ca.pem keep working
set -eu
APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"

if [ "$(id -u)" = "0" ]; then
  if [ -d /config-src ]; then
    rm -rf /config && mkdir -p /config
    cp -a /config-src/. /config/ 2>/dev/null || true
    chown -R "$APP_UID:$APP_GID" /config
    chmod 700 /config
    find /config -type f -exec chmod 600 {} +
  fi
  # output directories the collector writes to
  for d in /targets /probe; do
    if [ -d "$d" ] && [ "$(stat -c %u "$d")" != "$APP_UID" ]; then chown "$APP_UID:$APP_GID" "$d"; fi
  done
  exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups \
       --inh-caps=-all --bounding-set=-all --no-new-privs -- "$@"
fi
exec "$@"
