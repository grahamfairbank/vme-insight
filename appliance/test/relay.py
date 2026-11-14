#!/usr/bin/env python3
"""stdin/stdout <-> TCP relay, one per connection: QEMU guestfwd=...-cmd:relay.py host port."""
import os, select, socket, sys
s = socket.create_connection((sys.argv[1], int(sys.argv[2])))
fds = [0, s.fileno()]
while True:
    r, _, _ = select.select(fds, [], [])
    if 0 in r:
        d = os.read(0, 65536)
        if not d:
            s.shutdown(socket.SHUT_WR); fds.remove(0)
        else:
            s.sendall(d)
    if s.fileno() in r:
        d = s.recv(65536)
        if not d:
            break
        os.write(1, d)
