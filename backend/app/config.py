"""Configuración central de la aplicación.

La configuración falla de forma explícita (fail-fast) en producción cuando
falta un secreto o una variable crítica. En desarrollo/test se usan valores
seguros por defecto para no bloquear el arranque local.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} debe ser un número entero") from exc
    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} debe ser >= {minimum}")
    return value


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
IS_TEST = APP_ENV == "test"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("No se encontró DATABASE_URL en el archivo .env")
if IS_PRODUCTION and "CAMBIAR_PASSWORD" in DATABASE_URL:
    raise RuntimeError("DATABASE_URL contiene la contraseña de ejemplo; define una contraseña real")

# ── Secretos ────────────────────────────────────────────────────────────
_INSECURE_SECRETS = {
    "tu_clave_secreta_jwt_aqui_cambiar_en_produccion",
    "cambiar_por_un_secreto_de_al_menos_32_caracteres",
    "changeme",
    "secret",
    "buscador-default-jwt",
}


def _validate_secret(name: str, value: str, *, minimum: int = 32) -> str:
    if len(value) < minimum:
        raise RuntimeError(f"{name} debe tener al menos {minimum} caracteres")
    if value.lower() in _INSECURE_SECRETS:
        raise RuntimeError(f"{name} usa un valor por defecto inseguro; cámbialo")
    return value


JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if not JWT_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError(
            "JWT_SECRET es obligatorio en producción. Genera uno con: "
            "python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    JWT_SECRET = secrets.token_urlsafe(48)
    logger.warning("JWT_SECRET no configurado; se generó uno efímero para desarrollo")
else:
    JWT_SECRET = _validate_secret("JWT_SECRET", JWT_SECRET)

JWT_EXPIRATION_HOURS = _int("JWT_EXPIRATION_HOURS", 8, minimum=1)
JWT_COOKIE_NAME = os.getenv("JWT_COOKIE_NAME", "bp_access").strip() or "bp_access"
COOKIE_SECURE = _bool("COOKIE_SECURE", IS_PRODUCTION)
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "strict").strip().lower()
if COOKIE_SAMESITE not in {"strict", "lax", "none"}:
    raise RuntimeError("COOKIE_SAMESITE debe ser strict, lax o none")

# ── Acceso ──────────────────────────────────────────────────────────────
API_KEYS = _list("API_KEYS", [])
ALLOW_OPEN_ACCESS = _bool("ALLOW_OPEN_ACCESS", not IS_PRODUCTION)
if IS_PRODUCTION and ALLOW_OPEN_ACCESS:
    raise RuntimeError("ALLOW_OPEN_ACCESS no puede estar activo en producción")

ALLOWED_ORIGINS = _list(
    "ALLOWED_ORIGINS",
    []
    if IS_PRODUCTION
    else [
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
)
if IS_PRODUCTION and not ALLOWED_ORIGINS:
    logger.warning("ALLOWED_ORIGINS vacío en producción: solo se permitirá el mismo origen")

# ── Proxy / IP real ─────────────────────────────────────────────────────
TRUST_PROXY_HEADERS = _bool("TRUST_PROXY_HEADERS", False)
TRUSTED_PROXIES = _list("TRUSTED_PROXIES", [])

# ── Rate limiting ───────────────────────────────────────────────────────
RATE_LIMIT_MAX = _int("RATE_LIMIT_MAX", 30, minimum=1)
RATE_LIMIT_WINDOW = _int("RATE_LIMIT_WINDOW", 60, minimum=1)
SEARCH_RATE_LIMIT_MAX = _int("SEARCH_RATE_LIMIT_MAX", 60, minimum=1)
SEARCH_RATE_LIMIT_WINDOW = _int("SEARCH_RATE_LIMIT_WINDOW", 60, minimum=1)
LOGIN_RATE_LIMIT_MAX = _int("LOGIN_RATE_LIMIT_MAX", 5, minimum=1)
LOGIN_RATE_LIMIT_WINDOW = _int("LOGIN_RATE_LIMIT_WINDOW", 300, minimum=1)

# ── Caché ───────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHE_PREFIX = os.getenv("CACHE_PREFIX", "buscador").strip() or "buscador"
DNI_CACHE_TTL = _int("DNI_CACHE_TTL", 300, minimum=1)
BUSCAR_CACHE_TTL = _int("BUSCAR_CACHE_TTL", 60, minimum=1)
RUC_CACHE_TTL = _int("RUC_CACHE_TTL", 3600, minimum=1)
ARBOL_CACHE_TTL = _int("ARBOL_CACHE_TTL", 600, minimum=1)
NEGATIVE_CACHE_TTL = _int("NEGATIVE_CACHE_TTL", 30, minimum=1)

# ── RUC ─────────────────────────────────────────────────────────────────
RUC_API_KEY = os.getenv("RUC_API_KEY", "")
RUC_API_BASE = os.getenv("RUC_API_BASE", "https://peruapi.com/api")

# ── Familia ─────────────────────────────────────────────────────────────
FAMILIA_CANDIDATOS = _int("FAMILIA_CANDIDATOS", 300, minimum=10)
FAMILIA_LIMITE_DEFAULT = _int("FAMILIA_LIMITE_DEFAULT", 50, minimum=1)
FAMILIA_LIMITE_MAX = _int("FAMILIA_LIMITE_MAX", 200, minimum=1)
FAMILIA_UMBRAL_ALTA = _int("FAMILIA_UMBRAL_ALTA", 70, minimum=0)
FAMILIA_UMBRAL_MEDIA = _int("FAMILIA_UMBRAL_MEDIA", 50, minimum=0)
BUSCAR_CANDIDATOS = _int("BUSCAR_CANDIDATOS", 300, minimum=50)

# ── Administración inicial ──────────────────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
_INSECURE_ADMIN_PASSWORDS = {
    "cambiar_password_admin",
    "changeme",
    "admin",
    "password",
}
if IS_PRODUCTION and ADMIN_PASSWORD.lower() in _INSECURE_ADMIN_PASSWORDS:
    raise RuntimeError("ADMIN_PASSWORD usa un valor de ejemplo o demasiado común; cámbialo")
