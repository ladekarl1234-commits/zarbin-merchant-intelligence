# Live path-traversal probe against the running server, using a raw socket so `..`
# is NOT normalized by any client library. Proves the api.py spa() containment fix.
# Run with the server up: uv run python pipeline/probe_traversal.py
import socket

HOST, PORT = "127.0.0.1", 8630
PATHS = ["/../../pyproject.toml", "/../../data/marts/customers.parquet", "/..%2f..%2fpyproject.toml"]

fails = 0
for path in PATHS:
    s = socket.create_connection((HOST, PORT), timeout=5)
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
    leaked = b"[project]" in buf or b"name = \"zarin-intelligence\"" in buf or buf[:200].find(b"PAR1") != -1
    status = buf.split(b"\r\n", 1)[0].decode(errors="replace")
    print(f"{path:45} -> {status}  {'** LEAKED FILE **' if leaked else 'safe (no file bytes)'}")
    fails += 1 if leaked else 0

print("RESULT:", "SAFE — no traversal" if fails == 0 else f"{fails} LEAKS")
raise SystemExit(1 if fails else 0)
