# Live path-traversal probe against the running server, using a raw socket so `..`
# is NOT normalized by any client library. Proves the api.py spa() containment fix.
# Run with the server up: uv run python pipeline/probe_traversal.py
import socket
import time

HOST, PORT = "127.0.0.1", 8630
PATHS = ["/../../pyproject.toml", "/../../data/marts/customers.parquet", "/..%2f..%2fpyproject.toml",
         "///10.255.255.1/share/x"]  # UNC: must return fast (lexical reject), never open an SMB handle

fails = 0
for path in PATHS:
    t0 = time.time()
    s = socket.create_connection((HOST, PORT), timeout=8)
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: {HOST}\r\nConnection: close\r\n\r\n".encode())
    buf = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
        if len(buf) > 20000:
            break
    s.close()
    dt = time.time() - t0
    leaked = b"[project]" in buf or b"name = \"zarin-intelligence\"" in buf or buf[:400].find(b"PAR1") != -1
    slow = dt > 3.0  # a UNC/SMB connect would take many seconds; lexical reject is instant
    status = buf.split(b"\r\n", 1)[0].decode(errors="replace")
    verdict = "** LEAKED FILE **" if leaked else ("** SLOW (opened handle?) **" if slow else "safe (no file bytes)")
    print(f"{path:45} -> {status}  [{dt:.2f}s]  {verdict}")
    fails += 1 if (leaked or slow) else 0

print("RESULT:", "SAFE — no traversal" if fails == 0 else f"{fails} LEAKS")
raise SystemExit(1 if fails else 0)
