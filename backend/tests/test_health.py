from unittest.mock import patch


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_ready_when_db_up(client):
    res = client.get("/api/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready"}


def test_ready_when_db_down(client):
    with patch("app.main.engine.connect", side_effect=RuntimeError("db down")):
        res = client.get("/api/ready")
    assert res.status_code == 503


def test_cors_allows_frontend_origin(client):
    res = client.options(
        "/api/profiles",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-edit-token",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_unknown_origin(client):
    res = client.options(
        "/api/profiles",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in res.headers
