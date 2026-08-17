from sqlalchemy.exc import OperationalError

from tests.fakes import FakeEngine


def test_status_healthcheck_ok(client, monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "engine", FakeEngine([{"1": 1}]))
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["mensaje"] == "API operativa"
    assert data["database"] == "ok"


def test_status_healthcheck_error_db(client, monkeypatch):
    class FailingEngine:
        def connect(self):
            raise OperationalError("conn error", {}, Exception("DB down"))

    import app.main as main_mod

    monkeypatch.setattr(main_mod, "engine", FailingEngine())
    res = client.get("/api/status")
    assert res.status_code == 503
    assert "Base de datos no disponible" in res.json()["detail"] or "Servicio no disponible" in res.json()["detail"]


def test_security_headers_and_request_id(client, monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "engine", FakeEngine([{"1": 1}]))
    res = client.get("/api/status", headers={"X-Request-ID": "custom-uuid-1234"})
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == "custom-uuid-1234"
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
