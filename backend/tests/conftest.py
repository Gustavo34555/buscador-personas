import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("RUC_API_KEY", "")
os.environ.setdefault("API_KEYS", "")
os.environ.setdefault("FRONTEND_TOKEN_SECRET", "")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def limpiar_estado():
    from app.dependencies import ruc_rate_limiter, search_rate_limiter
    from app.routers import persona, ruc

    persona.dni_cache.clear()
    persona.buscar_cache.clear()
    search_rate_limiter.clear()
    ruc.ruc_cache.clear()
    ruc_rate_limiter.clear()
    yield
    persona.dni_cache.clear()
    persona.buscar_cache.clear()
    search_rate_limiter.clear()
    ruc.ruc_cache.clear()
    ruc_rate_limiter.clear()
