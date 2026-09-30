def test_metrics_counts_requests_by_route_template(client, created):
    profile, _ = created
    client.get(f"/api/profiles/{profile['tag']}")
    client.get("/api/profiles/nobody-here")

    body = client.get("/metrics").json()

    by_route = {(r["route"], r["status"]): r["count"] for r in body["by_route"]}
    assert by_route[("/api/profiles/{tag}", 200)] == 1
    assert by_route[("/api/profiles/{tag}", 404)] == 1
    assert body["window"]["requests"] >= 3
    assert body["window"]["p95"] is not None
    assert body["in_flight"] == 0
    assert "class" in body["db_pool"]


def test_metrics_requests_are_not_counted(client):
    client.get("/metrics")
    body = client.get("/metrics").json()
    assert all(not r["route"].startswith("/metrics") for r in body["by_route"])


def test_db_metrics_on_sqlite(client):
    assert client.get("/metrics/db").json() == {"engine": "sqlite"}
