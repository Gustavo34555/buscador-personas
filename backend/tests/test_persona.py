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


def test_persona_no_encontrada_cache_negativa(client, monkeypatch):
    engine = FakeEngine([])
    _mock_engine(monkeypatch, engine)
    assert client.get("/persona/99999998").status_code == 404
    assert client.get("/persona/99999998").status_code == 404
    assert engine.connect_count == 1


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


def test_buscar_cache_normaliza_tildes(client, monkeypatch):
    fila = dict(PERSONA_FILA)
    fila["dig_ruc"] = "5"
    engine = FakeEngine([fila])
    _mock_engine(monkeypatch, engine)
    assert client.get("/buscar", params={"q": "García"}).status_code == 200
    assert client.get("/buscar", params={"q": "Garcia"}).status_code == 200
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
    vary = [v.strip().lower() for v in res.headers.get("vary", "").split(",")]
    assert "accept-encoding" in vary


def test_buscar_reune_candidatos_aunque_limit_sea_menor(monkeypatch):
    """El re-ranking debe reunir hasta 300 candidatos, no solo `limit`."""
    from app.errors import QueryExecutionError  # noqa: F401  (documenta el tipo)
    from app.services import persona_service

    llamadas: list[str] = []

    def _fake_query(conn, sql, params, *, timeout_ms=2500, strict=True):
        llamadas.append(sql)
        if len(llamadas) == 1:
            return [{"dni": f"{i:08d}"} for i in range(25)]
        return []

    monkeypatch.setattr(persona_service, "_query_seguro", _fake_query)
    _mock_engine(monkeypatch, FakeEngine([]))

    persona_service.buscar_personas("juan garcia", "juan garcia", "juan garcia%", "", 2, 20)
    assert len(llamadas) == 3, "deben ejecutarse AND, prefijo y OR"


def test_timeout_sql_devuelve_503(client, monkeypatch):
    """Un timeout no debe disfrazarse de 'sin resultados' con 200."""
    from app.errors import QueryExecutionError

    def _boom(*args, **kwargs):
        raise QueryExecutionError("statement timeout")

    monkeypatch.setattr(persona_service, "buscar_personas", _boom)
    res = client.get("/buscar", params={"q": "juan garcia"})
    assert res.status_code == 503
    assert res.headers.get("retry-after") == "5"


def test_arbol_no_usa_cache_negativa_de_persona(client, monkeypatch):
    from app.routers import persona as router_persona
    from app.services import familia_service

    router_persona.dni_negative_cache.set("99999999", True)
    monkeypatch.setattr(familia_service, "engine", FakeEngine([PERSONA_FILA]))
    res = client.get("/persona/99999999/arbol")
    assert res.status_code == 200


def test_rank_preciso_no_depende_de_columnas_generadas():
    """El SQL debe funcionar aunque la base no tenga columnas generadas nuevas."""
    from app.sql.queries import CANDIDATOS_TSQUERY, RANK_PRECISO

    assert "p.nombre_busqueda" not in RANK_PRECISO
    assert "p.nombre_completo" not in RANK_PRECISO
    assert "AS nc_busq" in RANK_PRECISO
    assert "AS edad_anios" in RANK_PRECISO
    assert "det.edad_anios" in RANK_PRECISO
    # Rankear todos los matches antes del LIMIT hace que el OR expire.
    assert "ts_rank_cd" not in CANDIDATOS_TSQUERY


def test_query_familiar_tolerante_no_rompe_arbol():
    """Un timeout en una variante opcional no debe tumbar todo el árbol."""
    import pytest

    from app.errors import QueryExecutionError
    from app.services import familia_service as fs

    class BadConn:
        def execute(self, *args, **kwargs):
            raise RuntimeError("statement timeout")

    with pytest.raises(QueryExecutionError):
        fs._query(BadConn(), "SELECT 1", {}, strict=True)
    assert fs._query(BadConn(), "SELECT 1", {}, strict=False) == []
