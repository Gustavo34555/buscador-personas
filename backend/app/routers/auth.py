"""Router de autenticación: login, logout y perfil del usuario."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from app.config import JWT_EXPIRATION_HOURS
from app.dependencies import verify_login_rate_limit
from app.schemas import LoginRequest, LoginResponse, MeResponse
from app.security import clear_auth_cookie, require_jwt_auth, set_auth_cookie
from app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["autenticación"])


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    _rate_limit: None = Depends(verify_login_rate_limit),
):
    """Autentica al usuario y guarda el JWT en una cookie HttpOnly."""
    try:
        user = auth_service.verificar_credenciales(body.username, body.password)
    except SQLAlchemyError as exc:
        logger.exception("Error de base de datos durante el login")
        raise HTTPException(
            status_code=503,
            detail="Servicio de autenticación no disponible",
        ) from exc

    if not user:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = auth_service.crear_token(
        user["id"],
        user["username"],
        user["rol"],
        int(user.get("token_version") or 0),
    )
    set_auth_cookie(response, token)
    restantes = max(0, user["consultas_max"] - user["consultas_usadas"])

    return LoginResponse(
        token=token,
        username=user["username"],
        rol=user["rol"],
        consultas_restantes=restantes,
        expires_in=JWT_EXPIRATION_HOURS * 3600,
    )


@router.post("/logout", status_code=204)
def logout(response: Response):
    """Cierra la sesión eliminando la cookie HttpOnly."""
    clear_auth_cookie(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeResponse)
def me(payload: dict = Depends(require_jwt_auth)):
    """Devuelve información del usuario autenticado."""
    user_id = payload.get("sub")
    if not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(status_code=401, detail="Sesión de usuario requerida")

    try:
        user = auth_service.obtener_usuario_por_id(user_id)
    except SQLAlchemyError as exc:
        logger.exception("Error de base de datos al consultar el perfil")
        raise HTTPException(status_code=503, detail="Servicio no disponible") from exc

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return MeResponse(
        id=user["id"],
        username=user["username"],
        rol=user["rol"],
        consultas_max=user["consultas_max"],
        consultas_usadas=user["consultas_usadas"],
        consultas_restantes=max(0, user["consultas_max"] - user["consultas_usadas"]),
    )
