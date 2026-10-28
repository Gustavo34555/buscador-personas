import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("RUC_API_KEY", "")
os.environ.setdefault("API_KEYS", "")
os.environ.setdefault("ALLOW_OPEN_ACCESS", "true")
os.environ.setdefault("JWT_SECRET", "test-secret-para-pruebas-con-mas-de-32-caracteres")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def limpiar_estado():
    from app.dependencies import login_rate_limiter, ruc_rate_limiter, search_rate_limiter
    from app.routers import persona, ruc
    from app.services import auth_service

    def _limpiar():
        persona.dni_cache.clear()
        persona.buscar_cache.clear()
        persona.arbol_cache.clear()
        search_rate_limiter.clear()
        ruc.ruc_cache.clear()
        ruc_rate_limiter.clear()
        login_rate_limiter.clear()
        auth_service._sesion_cache.clear()

    _limpiar()
    yield
    _limpiar()
