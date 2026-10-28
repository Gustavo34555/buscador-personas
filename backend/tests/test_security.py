import app.security as security
from app.services import auth_service, persona_service
from tests.fakes import PERSONA_FILA, FakeEngine


def _token(user_id=2, rol="user"):
    return auth_service.crear_token(user_id, "testuser", rol)


def _mock_sesion(monkeypatch, user_id=2, rol="user"):
    monkeypatch.setattr(
        auth_service,
        "validar_sesion",
        lambda uid, ver: {
            "sub": uid,
            "username": "testuser",
            "rol": rol,
            "ver": ver,
        },
    )
    monkeypatch.setattr(auth_service, "consumir_consulta", lambda uid, es_admin=False: 49)


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


def test_api_key_no_puede_administrar(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    res = client.get("/api/admin/usuarios", headers={"X-API-Key": "clave-secreta"})
    assert res.status_code == 403


def test_jwt_bearer_pasa(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    _mock_sesion(monkeypatch)
    monkeypatch.setattr(persona_service, "engine", FakeEngine([PERSONA_FILA]))

    res = client.get(
        "/persona/12345678",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert res.status_code == 200


def test_jwt_cookie_pasa(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    _mock_sesion(monkeypatch)
    monkeypatch.setattr(persona_service, "engine", FakeEngine([PERSONA_FILA]))

    client.cookies.set(security.JWT_COOKIE_NAME, _token())
    res = client.get("/persona/12345678")
    assert res.status_code == 200


def test_jwt_invalido_falla(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])

    res = client.get(
        "/persona/12345678",
        headers={"Authorization": "Bearer token-falso-invalido"},
    )
    assert res.status_code == 401


def test_sesion_revocada_falla(client, monkeypatch):
    monkeypatch.setattr(security, "API_KEYS", ["clave-secreta"])
    monkeypatch.setattr(auth_service, "validar_sesion", lambda uid, ver: None)

    res = client.get(
        "/persona/12345678",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert res.status_code == 401
    assert "revocada" in res.json()["detail"]
