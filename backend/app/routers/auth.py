"""Router de autenticación: login y perfil del usuario."""

from fastapi import APIRouter, Depends

from app.schemas import LoginRequest, LoginResponse, MeResponse
from app.security import require_jwt_auth
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["autenticación"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    """Autentica al usuario y devuelve un JWT token."""
    user = auth_service.verificar_credenciales(body.username, body.password)
    if not user:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = auth_service.crear_token(user["id"], user["username"], user["rol"])
    restantes = max(0, user["consultas_max"] - user["consultas_usadas"])

    return LoginResponse(
        token=token,
        username=user["username"],
        rol=user["rol"],
        consultas_restantes=restantes,
    )


@router.get("/me", response_model=MeResponse)
def me(payload: dict = Depends(require_jwt_auth)):
    """Devuelve información del usuario autenticado."""
    user = auth_service.obtener_usuario_por_id(payload["sub"])
    if not user:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return MeResponse(
        id=user["id"],
        username=user["username"],
        rol=user["rol"],
        consultas_max=user["consultas_max"],
        consultas_usadas=user["consultas_usadas"],
        consultas_restantes=max(0, user["consultas_max"] - user["consultas_usadas"]),
    )
