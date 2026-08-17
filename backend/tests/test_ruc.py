from fastapi import HTTPException

from app.routers import ruc as ruc_router
from app.routers.ruc import get_ruc_service
from app.services import persona_service
from tests.fakes import FakeEngine

RUC_FILA = {"dni": "12345678", "dig_ruc": "5", "ap_pat": "Garcia", "ap_mat": "Perez", "nombres": "Juan"}

API_DATA = {
    "ruc": "10123456785",
    "razon_social": "GARCIA PEREZ JUAN CARLOS",
    "estado": "ACTIVO",
    "condicion": "HABIDO",
    "direccion": "AV LIMA 123",
    "departamento": "LIMA",
    "provincia": "LIMA",
    "distrito": "LIMA",
    "ubigeo": "150101",
}


class FakeRucService:
    def __init__(self, api_key="test-key", payload=None, error=None):
        self.api_key = api_key
        self.payload = payload
        self.error = error

    async def consultar(self, ruc):
        if self.error:
            raise self.error
        return self.payload if self.payload is not None else {}


def _setup(client, monkeypatch, service=None, fila=None):
    client.app.dependency_overrides[get_ruc_service] = lambda: service or FakeRucService()
    monkeypatch.setattr(persona_service, "engine", FakeEngine([fila] if fila else [RUC_FILA]))


def test_ruc_dni_invalido(client, monkeypatch):
    _setup(client, monkeypatch)
    res = client.get("/scraping/ruc/123")
    assert res.status_code == 400


def test_ruc_sin_api_key(client, monkeypatch):
    _setup(client, monkeypatch, service=FakeRucService(api_key=""))
    res = client.get("/scraping/ruc/12345678")
    assert res.status_code == 500
    assert "RUC_API_KEY" in res.json()["detail"]


def test_ruc_persona_sin_ruc(client, monkeypatch):
    _setup(client, monkeypatch, fila={**RUC_FILA, "dig_ruc": None})
    res = client.get("/scraping/ruc/12345678")
    assert res.status_code == 200
    assert res.json()["tiene_ruc"] is False


def test_ruc_ok(client, monkeypatch):
    _setup(client, monkeypatch, service=FakeRucService(payload=API_DATA))
    res = client.get("/scraping/ruc/12345678")
    assert res.status_code == 200
    body = res.json()
    assert body["tiene_ruc"] is True
    assert body["razon_social"] == API_DATA["razon_social"]
    assert body["ruc"] == "10123456785"


def test_ruc_api_404_devuelve_sin_ruc(client, monkeypatch):
    _setup(client, monkeypatch, service=FakeRucService(error=HTTPException(404, "no")))
    res = client.get("/scraping/ruc/12345678")
    assert res.status_code == 200
    assert res.json()["tiene_ruc"] is False


def test_ruc_api_401(client, monkeypatch):
    _setup(client, monkeypatch, service=FakeRucService(error=HTTPException(500, "RUC_API_KEY inválida")))
    res = client.get("/scraping/ruc/12345678")
    assert res.status_code == 500


def test_ruc_rate_limit(client, monkeypatch):
    from app.dependencies import ruc_rate_limiter
    ruc_rate_limiter.max_hits = 2
    ruc_rate_limiter.window = 60
    _setup(client, monkeypatch, service=FakeRucService(payload=API_DATA))
    try:
        for _ in range(2):
            ruc_router.ruc_cache.clear()
            assert client.get("/scraping/ruc/12345678", headers={"X-API-Key": "testkey1"}).status_code == 200
        ruc_router.ruc_cache.clear()
        res = client.get("/scraping/ruc/12345678", headers={"X-API-Key": "testkey1"})
        assert res.status_code == 429
        assert "retry-after" in res.headers
    finally:
        ruc_rate_limiter.max_hits = 30
        ruc_rate_limiter.clear()


def test_ruc_info_ruc_invalido(client, monkeypatch):
    _setup(client, monkeypatch)
    res = client.get("/scraping/ruc-info/123")
    assert res.status_code == 400


def test_ruc_info_ok(client, monkeypatch):
    _setup(client, monkeypatch, service=FakeRucService(payload=API_DATA))
    res = client.get("/scraping/ruc-info/10123456785")
    assert res.status_code == 200
    body = res.json()
    assert body["ruc"] == "10123456785"
    assert body["razon_social"] == API_DATA["razon_social"]


def test_ruc_info_404(client, monkeypatch):
    _setup(client, monkeypatch, service=FakeRucService(error=HTTPException(404, "RUC no encontrado")))
    res = client.get("/scraping/ruc-info/10123456785")
    assert res.status_code == 404
