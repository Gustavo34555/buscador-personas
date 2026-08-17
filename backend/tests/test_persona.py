
from app.services import persona_service
from tests.fakes import PERSONA_FILA, FakeEngine


def _mock_engine(monkeypatch, engine):
    monkeypatch.setattr(persona_service, "engine", engine)


def test_dni_invalido(client):
    for dni in ["123", "abcdefgh", "123456789"]:
        res = client.get(f"/persona/{dni}")
        assert res.status_code == 400


def test_persona_no_encontrada(client, monkeypatch):
    _mock_engine(monkeypatch, FakeEngine([]))
    res = client.get("/persona/99999999")
    assert res.status_code == 404


def test_persona_encontrada(client, monkeypatch):
    _mock_engine(monkeypatch, FakeEngine([PERSONA_FILA]))
    res = client.get("/persona/12345678")
    assert res.status_code == 200
    body = res.json()
    assert body["dni"] == "12345678"
    assert body["nombres"] == "Juan Carlos"
    assert body["sexo"] == "Masculino"


def test_persona_cache(client, monkeypatch):
    engine = FakeEngine([PERSONA_FILA])
    _mock_engine(monkeypatch, engine)
    first = client.get("/persona/12345678")
    second = client.get("/persona/12345678")
    assert first.status_code == second.status_code == 200
    assert engine.connect_count == 1


def test_buscar_query_vacio(client):
    res = client.get("/buscar", params={"q": "   "})
    assert res.status_code == 200
    assert res.json() == []


def test_buscar_resultados(client, monkeypatch):
    fila = dict(PERSONA_FILA)
    fila["dig_ruc"] = "5"
    _mock_engine(monkeypatch, FakeEngine([fila]))
    res = client.get("/buscar", params={"q": "Juan Garcia"})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["dni"] == "12345678"


def test_buscar_cache(client, monkeypatch):
    fila = dict(PERSONA_FILA)
    fila["dig_ruc"] = "5"
    engine = FakeEngine([fila])
    _mock_engine(monkeypatch, engine)
    client.get("/buscar", params={"q": "Juan"})
    client.get("/buscar", params={"q": "Juan"})
    assert engine.connect_count == 1


def test_buscar_query_corta(client):
    res = client.get("/buscar", params={"q": "ab"})
    assert res.status_code == 400


def test_buscar_limit_invalido(client):
    res = client.get("/buscar", params={"q": "Juan", "limit": 0})
    assert res.status_code == 422


def test_rate_limit_persona(client, monkeypatch):
    from app.dependencies import search_rate_limiter
    search_rate_limiter.max_hits = 2
    search_rate_limiter.window = 60
    _mock_engine(monkeypatch, FakeEngine([PERSONA_FILA]))
    try:
        headers = {"X-API-Key": "testkey1"}
        assert client.get("/persona/12345678", headers=headers).status_code == 200
        assert client.get("/persona/87654321", headers=headers).status_code == 200
        res = client.get("/persona/12345679", headers=headers)
        assert res.status_code == 429
        assert "retry-after" in res.headers
    finally:
        search_rate_limiter.max_hits = 60
        search_rate_limiter.clear()
