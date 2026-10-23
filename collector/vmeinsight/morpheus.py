"""Minimal client for the Morpheus / HPE VM Essentials REST API."""
import logging
import time

from urllib.parse import urlsplit, urlunsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status, path, body=""):
        super().__init__(f"HTTP {status} on {path}: {body[:200]}" if not isinstance(self, AuthError) else body)
        self.status = status
        self.path = path


class _PinnedAdapter(HTTPAdapter):
    """Accept only a certificate with this SHA-256 fingerprint (works with self-signed certs)."""

    def __init__(self, fingerprint, **kw):
        self.fingerprint = fingerprint.replace(":", "").lower()
        super().__init__(**kw)

    def init_poolmanager(self, *a, **kw):
        kw["assert_fingerprint"] = self.fingerprint
        kw["cert_reqs"] = "CERT_NONE"
        return super().init_poolmanager(*a, **kw)


def normalise_url(url, allow_http=False):
    """Add a scheme if missing and upgrade http to https unless allow_http is set."""
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme == "http" and not allow_http:
        log.warning("morpheus.url uses http://; switching to https:// so credentials are not sent "
                    "in clear text (set morpheus.allow_http: true to override)")
        parts = parts._replace(scheme="https")
    return urlunsplit(parts._replace(path=parts.path.rstrip("/")))


class AuthError(ApiError):
    """VME rejected the credentials. Raised without a traceback-worthy cause."""


AUTH_RETRY_AFTER = 900  # seconds to wait before trying a rejected login again (avoids account lockout)


class Morpheus:
    def __init__(self, cfg):
        self.base = normalise_url(cfg["url"], cfg.get("allow_http", False))
        self.username = cfg.get("username") or ""
        self.password = cfg.get("password") or ""
        self.static_token = cfg.get("api_token") or ""
        self.client_id = cfg.get("client_id") or "morph-api"
        self.timeout = int(cfg.get("timeout", 30))
        self.page_size = int(cfg.get("page_size", 250))
        self.s = requests.Session()
        fp = (cfg.get("tls_fingerprint") or "").strip()
        if fp:
            self.tls_mode = "pinned"
            self.s.verify = False
            self.s.mount("https://", _PinnedAdapter(fp))
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        elif cfg.get("ca_bundle"):
            self.tls_mode = "ca_bundle"
            self.s.verify = cfg["ca_bundle"]
        elif cfg.get("insecure") or cfg.get("verify_tls") is False:
            self.tls_mode = "insecure"
            self.s.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            log.warning("TLS certificate verification is OFF (morpheus.insecure). "
                        "Prefer morpheus.tls_fingerprint, see docs/CONFIGURATION.md")
        else:
            self.tls_mode = "verify"
            self.s.verify = True
        self.s.headers.update({"Accept": "application/json", "User-Agent": "vme-insight"})
        self._token = None
        self._expires = 0.0
        self._auth_failed_until = 0.0
        self._auth_failure = ""
        if not self.static_token and not (self.username and self.password):
            raise ValueError("morpheus: set api_token, or username and password")

    # -- auth -----------------------------------------------------------
    def _login(self):
        if time.time() < self._auth_failed_until:
            # don't hammer VME with a password it already rejected: repeated failures can lock the account
            raise AuthError(400, "/oauth/token", self._auth_failure + " (not retrying until "
                            + time.strftime("%H:%M", time.localtime(self._auth_failed_until)) + ")")
        r = self.s.post(
            f"{self.base}/oauth/token",
            params={"client_id": self.client_id, "grant_type": "password", "scope": "write"},
            data={"username": self.username, "password": self.password},
            timeout=self.timeout,
        )
        if (r.status_code in (400, 401) and "invalid_grant" in r.text) or r.status_code == 401:
            self._auth_failed_until = time.time() + AUTH_RETRY_AFTER
            self._auth_failure = (
                f"VME rejected the login for user '{self.username}' ({r.status_code} invalid_grant). Check "
                "morpheus.username and morpheus.password in config/config.yaml (put the password in single "
                "quotes), and that this account can log in to the VME UI and isn't locked or awaiting a "
                "password change. See docs/TROUBLESHOOTING.md#connecting-to-vme")
            raise AuthError(r.status_code, "/oauth/token", self._auth_failure)
        if r.status_code != 200:
            raise ApiError(r.status_code, "/oauth/token", r.text)
        self._auth_failed_until = 0.0
        j = r.json()
        self._token = j["access_token"]
        self._expires = time.time() + int(j.get("expires_in") or 3600)
        log.info("authenticated to %s as %s", self.base, self.username)

    def _bearer(self):
        if self.static_token:
            return self.static_token
        if not self._token or time.time() > self._expires - 300:
            self._login()
        return self._token

    # -- requests -------------------------------------------------------
    def get(self, path, params=None, auth=True):
        last = None
        for attempt in range(3):
            headers = {"Authorization": f"Bearer {self._bearer()}"} if auth else {}
            try:
                r = self.s.get(self.base + path, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401 and auth and not self.static_token and attempt == 0:
                self._token = None  # token revoked or expired early; log in again
                continue
            if r.status_code >= 500 and attempt < 2:
                last = ApiError(r.status_code, path, r.text)
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401 and auth and self.static_token:
                raise AuthError(401, path, "VME rejected morpheus.api_token (expired or revoked?). Generate a new "
                                "one under User Settings -> API Access, or use username and password instead.")
            if r.status_code != 200:
                raise ApiError(r.status_code, path, r.text)
            return r.json()
        raise last

    def list(self, path, key, params=None):
        """Fetch every page of a list endpoint.

        Returns (items, extras): extras merges any top-level dicts that sit
        beside the list (e.g. the per-id "stats" map on /api/instances)."""
        items, extras, offset = [], {}, 0
        while True:
            p = dict(params or {})
            p.update(max=self.page_size, offset=offset)
            j = self.get(path, p)
            page = j.get(key) or []
            items.extend(page)
            for k, v in j.items():
                if k not in (key, "meta") and isinstance(v, dict):
                    extras.setdefault(k, {}).update(v)
            total = (j.get("meta") or {}).get("total")
            offset += len(page)
            if not page or len(page) < self.page_size or (total is not None and offset >= int(total)):
                return items, extras
