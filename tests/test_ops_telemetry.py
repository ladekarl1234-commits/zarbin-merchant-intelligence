from zarin import ops_telemetry


def test_empty_api_stats_are_explicit(monkeypatch):
    monkeypatch.setattr(ops_telemetry, "_EVENTS", ops_telemetry.deque(maxlen=20))
    s = ops_telemetry.stats()
    assert s["requests"] == 0
    assert s["p95_latency_ms"] is None
    assert s["error_rate"] is None


def test_api_stats_aggregate_latency_errors_and_routes(monkeypatch):
    events = ops_telemetry.deque(maxlen=20)
    events.extend([
        {"route": "/api/overview", "method": "GET", "status": 200, "latency_ms": 100.0, "success": True},
        {"route": "/api/overview", "method": "GET", "status": 200, "latency_ms": 200.0, "success": True},
        {"route": "/api/admin/*", "method": "GET", "status": 500, "latency_ms": 400.0, "success": False},
    ])
    monkeypatch.setattr(ops_telemetry, "_EVENTS", events)
    s = ops_telemetry.stats()
    assert s["requests"] == 3
    assert abs(s["success_rate"] - 2 / 3) < 1e-12
    assert abs(s["error_rate"] - 1 / 3) < 1e-12
    assert s["avg_latency_ms"] == 700 / 3
    assert s["routes"]["/api/overview"] == 2
