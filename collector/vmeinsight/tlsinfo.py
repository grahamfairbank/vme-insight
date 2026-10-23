"""Show the VME manager's TLS certificate and the values to pin or trust it.

    docker compose run --rm collector python -m vmeinsight.tlsinfo [host[:port]]

With no argument the host comes from morpheus.url in config.yaml.
"""
import hashlib
import socket
import ssl
import sys
from urllib.parse import urlsplit

from . import config


def main(target=None):
    if not target:
        url = config.load()["morpheus"]["url"]
        target = urlsplit(url if "://" in url else "https://" + url).netloc
    host, _, port = target.partition(":")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, int(port or 443)), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    fp = hashlib.sha256(der).hexdigest().upper()
    pretty = ":".join(fp[i:i + 2] for i in range(0, len(fp), 2))
    print(f"# Certificate presented by {host}:{port or 443}")
    print(f"# SHA-256 fingerprint: {pretty}")
    print("#")
    print("# Copy the next line into the morpheus: section of config/config.yaml,")
    print('# replacing the empty tls_fingerprint: "" (keep the two leading spaces):')
    print(f'  tls_fingerprint: "{pretty}"')
    print("#")
    print("# Optional: confirm the fingerprint from another machine first (docs/INSTALL.md, step 4).")
    print("# Only if the manager has a certificate from your own CA: save the PEM below as")
    print("# config/vme-ca.pem and set  ca_bundle: /config/vme-ca.pem  instead.")
    print(ssl.DER_cert_to_PEM_cert(der), end="")


if __name__ == "__main__":
    main(*sys.argv[1:])
