import app.security as security
from app.services import persona_service
from tests.fakes import PERSONA_FILA, FakeEngine


def test_sin_api_key_es_401(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    res = client.get("/persona/12345678")
    assert res.status_code == 401


def test_api_key_incorrecta_es_401(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    res = client.get("/persona/12345678", headers={"X-API-Key": "otra"})
    assert res.status_code == 401


def test_api_key_correcta_pasa(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    monkeypatch.setattr(persona_service, "engine", FakeEngine([PERSONA_FILA]))
    res = client.get("/persona/12345678", headers={"X-API-Key": "clave-secreta"})
    assert res.status_code == 200


def test_api_key_requerida_en_buscar(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    res = client.get("/buscar", params={"q": "juan perez"})
    assert res.status_code == 401


def test_frontend_token_bearer_pasa(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    monkeypatch.setattr(security, "FRONTEND_TOKEN_SECRET", "mi-secreto-hmac-12345")
    monkeypatch.setattr(persona_service, "engine", FakeEngine([PERSONA_FILA]))

    # Obtener token
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "FRONTEND_TOKEN_SECRET", "mi-secreto-hmac-12345")
    res_tok = client.get("/api/frontend-token")
    assert res_tok.status_code == 200
    token = res_tok.json()["token"]
    assert token

    # Probar endpoint con Bearer token
    res = client.get("/persona/12345678", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


def test_frontend_token_invalido_falla(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    monkeypatch.setattr(security, "FRONTEND_TOKEN_SECRET", "mi-secreto-hmac-12345")

    res = client.get("/persona/12345678", headers={"Authorization": "Bearer token-falso-invalido"})
    assert res.status_code == 401
