import base64
import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from app.config import API_KEYS, FRONTEND_TOKEN_SECRET, FRONTEND_TOKEN_TTL


def _constant_time_in(key: str, valid_keys: list[str]) -> bool:
    """Verifica si *key* está en *valid_keys* con comparación en tiempo constante."""
    result = False
    for valid_key in valid_keys:
        if hmac.compare_digest(key, valid_key):
            result = True
    return result


def create_frontend_token() -> tuple[str, int]:
    """Genera un token HMAC temporal para el frontend."""
    ts = str(int(time.time()))
    exp = str(int(time.time()) + FRONTEND_TOKEN_TTL)
    payload = f"{ts}.{exp}"
    sig = hmac.new(
        FRONTEND_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()
    return token, FRONTEND_TOKEN_TTL


def _verify_frontend_token(token: str) -> bool:
    """Valida un token HMAC de sesión frontend."""
    if not FRONTEND_TOKEN_SECRET:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.rsplit(".", 2)
        if len(parts) != 3:
            return False
        ts, exp, sig = parts
        if time.time() > int(exp):
            return False
        payload = f"{ts}.{exp}"
        expected = hmac.new(
            FRONTEND_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def require_api_key(request: Request) -> None:
    """Exige autenticación en todos los endpoints de datos.

    Acepta:
    - Header ``X-API-Key`` con una clave válida (consumidores externos).
    - Header ``Authorization: Bearer <token>`` con un token de sesión
      generado por ``/api/frontend-token``.

    Si API_KEYS está vacío y FRONTEND_TOKEN_SECRET está vacío (entorno de
    desarrollo), el acceso queda abierto.
    """
    if not API_KEYS and not FRONTEND_TOKEN_SECRET:
        return

    # 1) API key clásica
    api_key = request.headers.get("X-API-Key", "")
    if api_key and API_KEYS and _constant_time_in(api_key, API_KEYS):
        return

    # 2) Token de sesión frontend
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and FRONTEND_TOKEN_SECRET:
        token = auth[7:]
        if _verify_frontend_token(token):
            return

    raise HTTPException(
        status_code=401,
        detail="Autenticación requerida. Envía X-API-Key o un token de sesión válido.",
        headers={"WWW-Authenticate": "API-Key"},
    )
