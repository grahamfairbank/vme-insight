#!/usr/bin/env python3
"""A minimal logging HTTP(S) forward proxy for appliance tests (boot-test.sh ISOLATED=1).

Handles CONNECT (https) and plain http requests, and prints one line per destination, so a test
can show which traffic went through the proxy. Test use only: no authentication, no limits.

  proxy.py [port]      (default 3128)
"""
import select
import socket
import sys
import threading
from datetime import datetime


def log(msg):
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def pipe(a, b):
    socks = [a, b]
    try:
        while True:
            r, _, _ = select.select(socks, [], [], 300)
            if not r:
                return
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return


def handle(c):
    try:
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = c.recv(65536)
            if not chunk:
                return
            head += chunk
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        method, target, _ = line.split(" ", 2)
        if method == "CONNECT":
            host, port = target.rsplit(":", 1)
            up = socket.create_connection((host, int(port)), timeout=30)
            c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            log(f"CONNECT {target}")
            rest = head.split(b"\r\n\r\n", 1)[1]
            if rest:
                up.sendall(rest)
        else:
            from urllib.parse import urlsplit
            u = urlsplit(target)
            up = socket.create_connection((u.hostname, u.port or 80), timeout=30)
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
            first, rest = head.split(b"\r\n", 1)
            up.sendall(f"{method} {path} HTTP/1.1\r\n".encode() + rest)
            log(f"{method} {u.hostname}{path[:60]}")
        pipe(c, up)
        up.close()
    except (OSError, ValueError) as e:
        log(f"error: {e}")
    finally:
        c.close()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3128
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(64)
    log(f"proxy listening on 127.0.0.1:{port}")
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
