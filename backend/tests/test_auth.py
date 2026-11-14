import pytest
from fastapi import HTTPException

from app.services import auth_service
from tests.fakes import PERSONA_FILA, FakeEngine

MOCK_USERS = {
    1: {
        "id": 1,
        "username": "admin",
        "password_hash": auth_service.hash_password("admin123"),
        "rol": "admin",
        "consultas_max": 999999,
        "consultas_usadas": 0,
        "activo": True,
        "token_version": 0,
        "created_at": "2026-08-24 10:00:00",
    },
    2: {
        "id": 2,
        "username": "testuser",
        "password_hash": auth_service.hash_password("pass1234"),
        "rol": "user",
        "consultas_max": 50,
        "consultas_usadas": 0,
        "activo": True,
        "token_version": 0,
        "created_at": "2026-08-24 10:00:00",
    },
}


@pytest.fixture(autouse=True)
def mock_auth_db(monkeypatch):
    def fake_verificar_credenciales(username, password):
        for u in MOCK_USERS.values():
            if u["username"] == username and u["activo"]:
                if auth_service.verify_password(password, u["password_hash"]):
                    return u
        return None

    def fake_obtener_usuario_por_id(user_id):
        return MOCK_USERS.get(user_id)

    def fake_validar_sesion(user_id, token_version):
        u = MOCK_USERS.get(user_id)
        if not u or not u["activo"] or u.get("token_version", 0) != token_version:
            return None
        return {
            "sub": u["id"],
            "username": u["username"],
            "rol": u["rol"],
            "ver": u.get("token_version", 0),
        }

    def fake_obtener_usuarios():
        return list(MOCK_USERS.values())

    def fake_crear_usuario(username, password, rol, consultas_max):
        if any(u["username"] == username for u in MOCK_USERS.values()):
            return None
        new_id = max(MOCK_USERS.keys()) + 1
        new_user = {
            "id": new_id,
            "username": username,
            "password_hash": auth_service.hash_password(password),
            "rol": rol,
            "consultas_max": consultas_max,
            "consultas_usadas": 0,
            "activo": True,
            "token_version": 0,
            "created_at": "2026-08-24 10:00:00",
        }
        MOCK_USERS[new_id] = new_user
        return new_user

    def fake_actualizar_usuario(user_id, consultas_max=None, activo=None, password=None):
        u = MOCK_USERS.get(user_id)
        if not u:
            return None
        if consultas_max is not None:
            u["consultas_max"] = consultas_max
        if activo is not None:
            u["activo"] = activo
            if not activo:
                u["token_version"] = u.get("token_version", 0) + 1
        if password is not None:
            u["password_hash"] = auth_service.hash_password(password)
            u["token_version"] = u.get("token_version", 0) + 1
        return u

    def fake_eliminar_usuario(user_id):
        u = MOCK_USERS.get(user_id)
        if not u or u["rol"] == "admin":
            return False
        del MOCK_USERS[user_id]
        return True

    def fake_consumir_consulta(user_id, es_admin=False):
        if es_admin:
            return None
        u = MOCK_USERS.get(user_id)
        if not u or u["consultas_usadas"] >= u["consultas_max"]:
            return None
        u["consultas_usadas"] += 1
        return u["consultas_max"] - u["consultas_usadas"]

    def fake_reembolsar_consulta(user_id):
        u = MOCK_USERS.get(user_id)
        if u:
            u["consultas_usadas"] = max(0, u["consultas_usadas"] - 1)

    monkeypatch.setattr(auth_service, "asegurar_admin", lambda: None)
    monkeypatch.setattr(auth_service, "verificar_credenciales", fake_verificar_credenciales)
    monkeypatch.setattr(auth_service, "obtener_usuario_por_id", fake_obtener_usuario_por_id)
    monkeypatch.setattr(auth_service, "validar_sesion", fake_validar_sesion)
    monkeypatch.setattr(auth_service, "obtener_usuarios", fake_obtener_usuarios)
    monkeypatch.setattr(auth_service, "crear_usuario", fake_crear_usuario)
    monkeypatch.setattr(auth_service, "actualizar_usuario", fake_actualizar_usuario)
    monkeypatch.setattr(auth_service, "eliminar_usuario", fake_eliminar_usuario)
    monkeypatch.setattr(auth_service, "consumir_consulta", fake_consumir_consulta)
    monkeypatch.setattr(auth_service, "reembolsar_consulta", fake_reembolsar_consulta)


def _login(client, username="admin", password="admin123"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_login_exitoso_guarda_cookie(client):
    response = _login(client)
    assert response.status_code == 200
    data = response.json()
    assert data["token"]
    assert data["username"] == "admin"
    assert data["rol"] == "admin"

    cookie = response.headers.get("set-cookie", "")
    assert "bp_access=" in cookie
    assert "HttpOnly" in cookie


def test_login_fallido(client):
    response = _login(client, password="wrongpassword")
    assert response.status_code == 401
    assert "incorrectos" in response.json()["detail"]


def test_me_endpoint_cookie_y_bearer(client):
    login_res = _login(client)
    token = login_res.json()["token"]

    # La cookie se guarda automáticamente en el cliente.
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "admin"

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["rol"] == "admin"


def test_logout_elimina_cookie(client):
    _login(client)
    assert client.get("/api/auth/me").status_code == 200

    res = client.post("/api/auth/logout")
    assert res.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_admin_crud_usuarios(client):
    login_res = _login(client)
    headers = {"Authorization": f"Bearer {login_res.json()['token']}"}

    create_res = client.post(
        "/api/admin/usuarios",
        headers=headers,
        json={"username": "nuevo_usuario", "password": "password123", "consultas_max": 50},
    )
    assert create_res.status_code == 201
    user_data = create_res.json()
    user_id = user_data["id"]
    assert user_data["username"] == "nuevo_usuario"
    assert user_data["consultas_max"] == 50

    list_res = client.get("/api/admin/usuarios", headers=headers)
    assert list_res.status_code == 200
    assert any(u["username"] == "nuevo_usuario" for u in list_res.json())

    update_res = client.put(
        f"/api/admin/usuarios/{user_id}",
        headers=headers,
        json={"consultas_max": 150},
    )
    assert update_res.status_code == 200
    assert update_res.json()["consultas_max"] == 150

    del_res = client.delete(f"/api/admin/usuarios/{user_id}", headers=headers)
    assert del_res.status_code == 204


def test_admin_no_puede_desactivarse(client):
    login_res = _login(client)
    headers = {"Authorization": f"Bearer {login_res.json()['token']}"}

    res = client.put("/api/admin/usuarios/1", headers=headers, json={"activo": False})
    assert res.status_code == 400


def test_usuario_sin_consultas(client, monkeypatch):
    from app.services import persona_service

    MOCK_USERS[99] = {
        "id": 99,
        "username": "user_zero",
        "password_hash": "hash",
        "rol": "user",
        "consultas_max": 0,
        "consultas_usadas": 0,
        "activo": True,
        "token_version": 0,
        "created_at": "2026-08-24",
    }
    token = auth_service.crear_token(99, "user_zero", "user")
    monkeypatch.setattr(persona_service, "engine", FakeEngine([PERSONA_FILA]))

    search_res = client.get("/persona/12345678", headers={"Authorization": f"Bearer {token}"})
    assert search_res.status_code == 403
    assert "Sin consultas disponibles" in search_res.json()["detail"]


def test_consulta_exitosa_descuenta_y_404_reembolsa(client, monkeypatch):
    from app.services import persona_service

    token = auth_service.crear_token(2, "testuser", "user")
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(persona_service, "engine", FakeEngine([PERSONA_FILA]))
    MOCK_USERS[2]["consultas_usadas"] = 0

    res = client.get("/persona/12345678", headers=headers)
    assert res.status_code == 200
    assert res.headers["X-Consultas-Restantes"] == "49"
    assert MOCK_USERS[2]["consultas_usadas"] == 1

    # Un DNI inexistente no debe consumir la cuota.
    monkeypatch.setattr(persona_service, "engine", FakeEngine([]))
    assert client.get("/persona/99999999", headers=headers).status_code == 404
    assert MOCK_USERS[2]["consultas_usadas"] == 1


class FakeRucService:
    api_key = "test-key"

    def __init__(self, error=None):
        self.error = error

    async def consultar(self, ruc):
        if self.error:
            raise self.error
        return {
            "ruc": ruc,
            "razon_social": "PEREZ GOMEZ JUAN CARLOS",
            "estado": "ACTIVO",
            "condicion": "HABIDO",
            "direccion": "AV LIMA 123",
        }


def _ruc_headers():
    token = auth_service.crear_token(2, "testuser", "user")
    return {"Authorization": f"Bearer {token}"}


def test_ruc_descuenta_cuota_y_expone_saldo(client, monkeypatch):
    from app.routers.ruc import get_ruc_service
    from app.services import persona_service

    monkeypatch.setattr(
        persona_service, "engine", FakeEngine([{"dni": "12345678", "dig_ruc": "5"}])
    )
    client.app.dependency_overrides[get_ruc_service] = lambda: FakeRucService()
    MOCK_USERS[2]["consultas_usadas"] = 0
    try:
        res = client.get("/scraping/ruc/12345678", headers=_ruc_headers())
        assert res.status_code == 200
        assert res.headers["X-Consultas-Restantes"] == "49"
        assert MOCK_USERS[2]["consultas_usadas"] == 1

        # La caché del servidor acelera la respuesta, pero sigue descontando.
        res = client.get("/scraping/ruc/12345678", headers=_ruc_headers())
        assert res.status_code == 200
        assert res.headers["X-Consultas-Restantes"] == "48"
        assert MOCK_USERS[2]["consultas_usadas"] == 2
    finally:
        client.app.dependency_overrides.pop(get_ruc_service, None)


def test_ruc_error_reembolsa_cuota(client, monkeypatch):
    from app.routers.ruc import get_ruc_service
    from app.services import persona_service

    monkeypatch.setattr(
        persona_service, "engine", FakeEngine([{"dni": "12345678", "dig_ruc": "5"}])
    )
    service = FakeRucService(error=HTTPException(500, "SUNAT no disponible"))
    client.app.dependency_overrides[get_ruc_service] = lambda: service
    MOCK_USERS[2]["consultas_usadas"] = 0
    try:
        res = client.get("/scraping/ruc/12345678", headers=_ruc_headers())
        assert res.status_code == 500
        assert MOCK_USERS[2]["consultas_usadas"] == 0
    finally:
        client.app.dependency_overrides.pop(get_ruc_service, None)


def test_ruc_info_expone_saldo(client, monkeypatch):
    from app.routers.ruc import get_ruc_service

    client.app.dependency_overrides[get_ruc_service] = lambda: FakeRucService()
    MOCK_USERS[2]["consultas_usadas"] = 0
    try:
        res = client.get("/scraping/ruc-info/10123456785", headers=_ruc_headers())
        assert res.status_code == 200
        assert res.headers["X-Consultas-Restantes"] == "49"
        assert MOCK_USERS[2]["consultas_usadas"] == 1
    finally:
        client.app.dependency_overrides.pop(get_ruc_service, None)


def test_ruc_info_404_reembolsa(client, monkeypatch):
    from app.routers.ruc import get_ruc_service

    service = FakeRucService(error=HTTPException(404, "RUC no encontrado"))
    client.app.dependency_overrides[get_ruc_service] = lambda: service
    MOCK_USERS[2]["consultas_usadas"] = 0
    try:
        res = client.get("/scraping/ruc-info/10123456785", headers=_ruc_headers())
        assert res.status_code == 404
        assert MOCK_USERS[2]["consultas_usadas"] == 0
    finally:
        client.app.dependency_overrides.pop(get_ruc_service, None)
