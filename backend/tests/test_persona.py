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


def test_buscar_normalizacion_tildes(client, monkeypatch):
    fila = dict(PERSONA_FILA)
    fila["dig_ruc"] = "5"
    _mock_engine(monkeypatch, FakeEngine([fila]))
    # Con tilde debe procesarse sin errores y normalizarse
    res = client.get("/buscar", params={"q": "García Pérez"})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["dni"] == "12345678"


def test_buscar_orden_tokens(client, monkeypatch):
    fila = dict(PERSONA_FILA)
    fila["dig_ruc"] = "5"
    _mock_engine(monkeypatch, FakeEngine([fila]))
    # Orden natural: Paterno Materno Nombre
    res = client.get("/buscar", params={"q": "Garcia Perez Juan"})
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


def test_arbol_dni_invalido(client):
    res = client.get("/persona/123/arbol")
    assert res.status_code == 400


def test_arbol_persona_encontrada(client, monkeypatch):
    from app.services import familia_service

    monkeypatch.setattr(familia_service, "engine", FakeEngine([PERSONA_FILA]))
    res = client.get("/persona/12345678/arbol")
    assert res.status_code == 200
    body = res.json()
    assert "persona" in body
    assert body["persona"]["dni"] == "12345678"
    assert "hijos" in body
    assert "hermanos" in body
    assert "meta" in body


def test_c4_dni_invalido(client):
    res = client.get("/persona/123/c4")
    assert res.status_code == 400


def test_c4_persona_encontrada(client, monkeypatch):
    _mock_engine(monkeypatch, FakeEngine([PERSONA_FILA]))
    res = client.get("/persona/12345678/c4")
    assert res.status_code == 200
    body = res.json()
    assert body["codigo_referencia"].startswith("REF-")
    assert body["fecha_generacion"]
    assert body["es_oficial"] is False
    assert body["aviso"]
    assert "mrz_linea1" not in body
    assert "firma_digital" not in body
    assert "url_verificacion" not in body
    assert body["persona"]["dni"] == "12345678"


def test_headers_privacidad_y_timing(client):
    res = client.get("/persona/123")
    assert res.status_code == 400
    assert res.headers["cache-control"].startswith("no-store")
    assert res.headers["pragma"] == "no-cache"
    assert "server-timing" in res.headers
    assert "app;dur=" in res.headers["server-timing"]
    csp = res.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp


def test_cache_headers_estaticos(client):
    root = client.get("/")
    assert root.status_code == 200
    assert root.headers["cache-control"] == "no-cache"

    versioned = client.get("/styles.css", params={"v": "2.6"})
    assert versioned.status_code == 200
    assert versioned.headers["cache-control"] == "public, max-age=31536000, immutable"

    font = client.get("/fonts/inter-latin.woff2")
    assert font.status_code == 200
    assert font.headers["cache-control"] == "public, max-age=604800"

    service_worker = client.get("/sw.js")
    assert service_worker.status_code == 200
    assert service_worker.headers["cache-control"] == "no-cache"


def test_gzip_respuestas_grandes(client):
    res = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers.get("content-encoding") == "gzip"
    assert res.headers.get("vary") == "Accept-Encoding"
