from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Response

from app.config import (
    ALLOW_OPEN_ACCESS,
    API_KEYS,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    JWT_COOKIE_NAME,
    JWT_EXPIRATION_HOURS,
)
from app.services import auth_service


def _constant_time_in(key: str, valid_keys: list[str]) -> bool:
    """Verifica si *key* está en *valid_keys* con comparación en tiempo constante."""
    result = False
    for valid_key in valid_keys:
        if hmac.compare_digest(key, valid_key):
            result = True
    return result


def _extract_tokens(request: Request) -> list[str]:
    """Devuelve los tokens candidatos: cookie HttpOnly y/o Bearer."""
    tokens: list[str] = []
    cookie = request.cookies.get(JWT_COOKIE_NAME)
    if cookie:
        tokens.append(cookie)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        bearer = auth[7:].strip()
        if bearer and bearer not in tokens:
            tokens.append(bearer)
    return tokens


def require_jwt_auth(request: Request) -> dict:
    """Exige autenticación por JWT (cookie o Bearer) o API key.

    - JWT de usuario: devuelve el payload con ``sub``, ``rol`` y ``ver``.
    - API key: devuelve un principal de solo lectura de datos (nunca admin).
    - Modo abierto: solo si ``ALLOW_OPEN_ACCESS`` está activo (desarrollo/test).
    """
    for token in _extract_tokens(request):
        payload = auth_service.verificar_token(token)
        if not payload:
            continue

        user_id = payload.get("sub")
        token_version = int(payload.get("ver") or 0)
        if not isinstance(user_id, int):
            continue

        valid = auth_service.validar_sesion(user_id, token_version)
        if valid:
            return valid

        raise HTTPException(
            status_code=401,
            detail="Sesión expirada o revocada. Inicia sesión nuevamente.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key = request.headers.get("X-API-Key", "")
    if api_key and API_KEYS and _constant_time_in(api_key, API_KEYS):
        # Una API key no debe poder administrar usuarios ni cambiar datos.
        return {
            "sub": 0,
            "username": "api_key_client",
            "rol": "user",
            "ver": 0,
            "scopes": ["data:read"],
        }

    if ALLOW_OPEN_ACCESS and not API_KEYS:
        return {
            "sub": 0,
            "username": "dev_user",
            "rol": "user",
            "ver": 0,
            "scopes": ["data:read"],
        }

    raise HTTPException(
        status_code=401,
        detail="Autenticación requerida. Inicia sesión o envía X-API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(request: Request) -> dict:
    """Exige autenticación JWT con rol admin."""
    payload = require_jwt_auth(request)
    if payload.get("rol") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado. Se requiere rol de administrador.",
        )
    return payload


def require_api_key(request: Request) -> None:
    """Alias histórico: exige autenticación de datos (JWT o API key)."""
    require_jwt_auth(request)


def set_auth_cookie(response: Response, token: str) -> None:
    """Guarda el JWT en una cookie HttpOnly y SameSite=Strict."""
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=JWT_EXPIRATION_HOURS * 3600,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=JWT_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )
