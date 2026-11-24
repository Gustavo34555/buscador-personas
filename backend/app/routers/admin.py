"""Router de administración: CRUD de usuarios (solo admin)."""


from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import ActualizarUsuarioRequest, CrearUsuarioRequest, UsuarioResponse
from app.security import require_admin, verify_csrf_header
from app.services import auth_service

router = APIRouter(
    prefix="/api/admin",
    tags=["administración"],
    dependencies=[Depends(verify_csrf_header)],
)


def _serializar(usuario: dict) -> dict:
    usuario["created_at"] = str(usuario["created_at"]) if usuario.get("created_at") else None
    return usuario


@router.get("/usuarios", response_model=list[UsuarioResponse])
def listar_usuarios(_admin: dict = Depends(require_admin)):
    """Lista todos los usuarios del sistema."""
    return [_serializar(u) for u in auth_service.obtener_usuarios()]


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201)
def crear_usuario(body: CrearUsuarioRequest, _admin: dict = Depends(require_admin)):
    """Crea un nuevo usuario con la cantidad de consultas especificada."""
    try:
        user = auth_service.crear_usuario(body.username, body.password, "user", body.consultas_max)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not user:
        raise HTTPException(status_code=409, detail=f"El usuario '{body.username}' ya existe")

    return _serializar(user)


@router.put("/usuarios/{user_id}", response_model=UsuarioResponse)
def actualizar_usuario(
    user_id: int,
    body: ActualizarUsuarioRequest,
    admin: dict = Depends(require_admin),
):
    """Actualiza consultas_max, activo o contraseña de un usuario."""
    if user_id == admin.get("sub") and body.activo is False:
        raise HTTPException(
            status_code=400,
            detail="No puedes desactivar tu propia cuenta de administrador",
        )

    try:
        user = auth_service.actualizar_usuario(
            user_id,
            consultas_max=body.consultas_max,
            activo=body.activo,
            password=body.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return _serializar(user)


@router.delete("/usuarios/{user_id}", status_code=204)
def eliminar_usuario(user_id: int, admin: dict = Depends(require_admin)):
    """Elimina un usuario. No se puede eliminar al admin ni a uno mismo."""
    if user_id == admin.get("sub"):
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta")

    if not auth_service.eliminar_usuario(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado o es administrador")
