import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth_service

client = TestClient(app)


# Mock user store for unit tests
MOCK_USERS = {
    1: {
        "id": 1,
        "username": "admin",
        "password_hash": auth_service.hash_password("admin123"),
        "rol": "admin",
        "consultas_max": 999999,
        "consultas_usadas": 0,
        "activo": True,
        "created_at": "2026-08-24 10:00:00",
    },
    2: {
        "id": 2,
        "username": "testuser",
        "password_hash": auth_service.hash_password("pass123"),
        "rol": "user",
        "consultas_max": 50,
        "consultas_usadas": 0,
        "activo": True,
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
        if password is not None:
            u["password_hash"] = auth_service.hash_password(password)
        return u

    def fake_eliminar_usuario(user_id):
        u = MOCK_USERS.get(user_id)
        if not u or u["rol"] == "admin":
            return False
        del MOCK_USERS[user_id]
        return True

    def fake_consultas_restantes(user_id):
        u = MOCK_USERS.get(user_id)
        if not u:
            return 0
        return max(0, u["consultas_max"] - u["consultas_usadas"])

    def fake_descontar_consulta(user_id):
        u = MOCK_USERS.get(user_id)
        if not u or u["consultas_usadas"] >= u["consultas_max"]:
            return False
        u["consultas_usadas"] += 1
        return True

    monkeypatch.setattr(auth_service, "verificar_credenciales", fake_verificar_credenciales)
    monkeypatch.setattr(auth_service, "obtener_usuario_por_id", fake_obtener_usuario_por_id)
    monkeypatch.setattr(auth_service, "obtener_usuarios", fake_obtener_usuarios)
    monkeypatch.setattr(auth_service, "crear_usuario", fake_crear_usuario)
    monkeypatch.setattr(auth_service, "actualizar_usuario", fake_actualizar_usuario)
    monkeypatch.setattr(auth_service, "eliminar_usuario", fake_eliminar_usuario)
    monkeypatch.setattr(auth_service, "consultas_restantes", fake_consultas_restantes)
    monkeypatch.setattr(auth_service, "descontar_consulta", fake_descontar_consulta)


def test_login_exitoso():
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["username"] == "admin"
    assert data["rol"] == "admin"


def test_login_fallido():
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert response.status_code == 401
    assert "incorrectos" in response.json()["detail"]


def test_me_endpoint():
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_res.json()["token"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "admin"
    assert data["rol"] == "admin"


def test_admin_crud_usuarios():
    # Login as admin
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    admin_token = login_res.json()["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Crear nuevo usuario de prueba
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

    # 2. Listar usuarios
    list_res = client.get("/api/admin/usuarios", headers=headers)
    assert list_res.status_code == 200
    assert any(u["username"] == "nuevo_usuario" for u in list_res.json())

    # 3. Actualizar consultas del usuario
    update_res = client.put(
        f"/api/admin/usuarios/{user_id}",
        headers=headers,
        json={"consultas_max": 150},
    )
    assert update_res.status_code == 200
    assert update_res.json()["consultas_max"] == 150

    # 4. Eliminar usuario de prueba
    del_res = client.delete(f"/api/admin/usuarios/{user_id}", headers=headers)
    assert del_res.status_code == 204


def test_usuario_sin_consultas():
    # Create zero-query user
    token = auth_service.crear_token(99, "user_zero", "user")
    MOCK_USERS[99] = {
        "id": 99,
        "username": "user_zero",
        "password_hash": "hash",
        "rol": "user",
        "consultas_max": 0,
        "consultas_usadas": 0,
        "activo": True,
        "created_at": "2026-08-24",
    }

    search_res = client.get("/persona/12345678", headers={"Authorization": f"Bearer {token}"})
    assert search_res.status_code == 403
    assert "Sin consultas disponibles" in search_res.json()["detail"]
