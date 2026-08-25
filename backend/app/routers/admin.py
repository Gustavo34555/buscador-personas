"""Router de administración: CRUD de usuarios (solo admin)."""

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import ActualizarUsuarioRequest, CrearUsuarioRequest, UsuarioResponse
from app.security import require_admin
from app.services import auth_service

router = APIRouter(prefix="/api/admin", tags=["administración"])


@router.get("/usuarios", response_model=list[UsuarioResponse])
def listar_usuarios(_admin: dict = Depends(require_admin)):
    """Lista todos los usuarios del sistema."""
    usuarios = auth_service.obtener_usuarios()
    result = []
    for u in usuarios:
        u["created_at"] = str(u["created_at"]) if u.get("created_at") else None
        result.append(u)
    return result


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201)
def crear_usuario(body: CrearUsuarioRequest, _admin: dict = Depends(require_admin)):
    """Crea un nuevo usuario con la cantidad de consultas especificada."""
    if len(body.username) < 3:
        raise HTTPException(status_code=400, detail="El nombre de usuario debe tener al menos 3 caracteres")
    if len(body.password) < 4:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 4 caracteres")
    if body.consultas_max < 0:
        raise HTTPException(status_code=400, detail="La cantidad de consultas debe ser positiva")

    user = auth_service.crear_usuario(body.username, body.password, "user", body.consultas_max)
    if not user:
        raise HTTPException(status_code=409, detail=f"El usuario '{body.username}' ya existe")

    user["created_at"] = str(user["created_at"]) if user.get("created_at") else None
    return user


@router.put("/usuarios/{user_id}", response_model=UsuarioResponse)
def actualizar_usuario(user_id: int, body: ActualizarUsuarioRequest, _admin: dict = Depends(require_admin)):
    """Actualiza consultas_max, activo o contraseña de un usuario."""
    user = auth_service.actualizar_usuario(
        user_id,
        consultas_max=body.consultas_max,
        activo=body.activo,
        password=body.password,
    )
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user["created_at"] = str(user["created_at"]) if user.get("created_at") else None
    return user


@router.delete("/usuarios/{user_id}", status_code=204)
def eliminar_usuario(user_id: int, _admin: dict = Depends(require_admin)):
    """Elimina un usuario. No se puede eliminar al admin."""
    if not auth_service.eliminar_usuario(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado o es administrador")
