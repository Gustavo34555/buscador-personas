"""Servicio de autenticación: JWT, bcrypt y control de consultas."""

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import JWT_EXPIRATION_HOURS, JWT_SECRET
from app.db import engine

logger = logging.getLogger(__name__)


# ── Hashing de contraseñas ──────────────────────────────────────

def hash_password(password: str) -> str:
    """Genera un hash bcrypt de la contraseña."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica una contraseña contra su hash bcrypt."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ── JWT Tokens ──────────────────────────────────────────────────

def crear_token(user_id: int, username: str, rol: str) -> str:
    """Genera un JWT firmado con los datos del usuario."""
    payload = {
        "sub": str(user_id),
        "username": username,
        "rol": rol,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verificar_token(token: str) -> dict | None:
    """Decodifica y valida un JWT. Retorna el payload con sub convertido a int o None."""
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if "sub" in decoded:
            decoded["sub"] = int(decoded["sub"])
        return decoded
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ── Operaciones de usuario ──────────────────────────────────────

def verificar_credenciales(username: str, password: str) -> dict | None:
    """Valida las credenciales y retorna los datos del usuario, o None."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, password_hash, rol, consultas_max, consultas_usadas, activo FROM usuarios WHERE username = :username"),
                {"username": username},
            ).mappings().first()

        if not row:
            return None

        user = dict(row)
        if not user["activo"]:
            return None

        if not verify_password(password, user["password_hash"]):
            return None

        return user
    except SQLAlchemyError:
        logger.exception("Error al verificar credenciales para %s", username)
        return None


def obtener_usuario_por_id(user_id: int) -> dict | None:
    """Obtiene un usuario por su ID."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, rol, consultas_max, consultas_usadas, activo, created_at FROM usuarios WHERE id = :id"),
                {"id": user_id},
            ).mappings().first()
            return dict(row) if row else None
    except SQLAlchemyError:
        logger.exception("Error al obtener usuario %d", user_id)
        return None


def descontar_consulta(user_id: int) -> bool:
    """Incrementa consultas_usadas en 1. Retorna True si se pudo descontar."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    UPDATE usuarios
                    SET consultas_usadas = consultas_usadas + 1
                    WHERE id = :id AND activo = true AND consultas_usadas < consultas_max
                    RETURNING id
                """),
                {"id": user_id},
            )
            conn.commit()
            return result.rowcount > 0
    except SQLAlchemyError:
        logger.exception("Error al descontar consulta para usuario %d", user_id)
        return False


def consultas_restantes(user_id: int) -> int:
    """Retorna las consultas restantes del usuario."""
    user = obtener_usuario_por_id(user_id)
    if not user:
        return 0
    return max(0, user["consultas_max"] - user["consultas_usadas"])


def obtener_usuarios() -> list[dict]:
    """Lista todos los usuarios (para el admin)."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, username, rol, consultas_max, consultas_usadas, activo, created_at FROM usuarios ORDER BY id")
            ).mappings().all()
            return [dict(r) for r in rows]
    except SQLAlchemyError:
        logger.exception("Error al listar usuarios")
        return []


def crear_usuario(username: str, password: str, rol: str, consultas_max: int) -> dict | None:
    """Crea un nuevo usuario. Retorna sus datos o None si ya existe."""
    pw_hash = hash_password(password)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO usuarios (username, password_hash, rol, consultas_max, consultas_usadas, activo)
                    VALUES (:username, :password_hash, :rol, :consultas_max, 0, true)
                    RETURNING id, username, rol, consultas_max, consultas_usadas, activo, created_at
                """),
                {"username": username, "password_hash": pw_hash, "rol": rol, "consultas_max": consultas_max},
            ).mappings().first()
            conn.commit()
            return dict(row) if row else None
    except SQLAlchemyError as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            return None
        logger.exception("Error al crear usuario %s", username)
        return None


def actualizar_usuario(user_id: int, consultas_max: int | None = None, activo: bool | None = None, password: str | None = None) -> dict | None:
    """Actualiza campos de un usuario existente."""
    sets = []
    params: dict = {"id": user_id}

    if consultas_max is not None:
        sets.append("consultas_max = :consultas_max")
        params["consultas_max"] = consultas_max

    if activo is not None:
        sets.append("activo = :activo")
        params["activo"] = activo

    if password is not None:
        sets.append("password_hash = :password_hash")
        params["password_hash"] = hash_password(password)

    if not sets:
        return obtener_usuario_por_id(user_id)

    query = f"UPDATE usuarios SET {', '.join(sets)} WHERE id = :id RETURNING id, username, rol, consultas_max, consultas_usadas, activo, created_at"

    try:
        with engine.connect() as conn:
            row = conn.execute(text(query), params).mappings().first()
            conn.commit()
            return dict(row) if row else None
    except SQLAlchemyError:
        logger.exception("Error al actualizar usuario %d", user_id)
        return None


def eliminar_usuario(user_id: int) -> bool:
    """Elimina un usuario por su ID. No permite eliminar admins."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM usuarios WHERE id = :id AND rol != 'admin' RETURNING id"),
                {"id": user_id},
            )
            conn.commit()
            return result.rowcount > 0
    except SQLAlchemyError:
        logger.exception("Error al eliminar usuario %d", user_id)
        return False
