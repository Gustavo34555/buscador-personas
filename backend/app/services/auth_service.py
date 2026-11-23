"""Servicio de autenticación: JWT, bcrypt y control de consultas."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.cache import TTLCache
from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, JWT_EXPIRATION_HOURS, JWT_SECRET
from app.db import engine

logger = logging.getLogger(__name__)

# Hash de relleno para que un usuario inexistente tarde lo mismo que uno real.
_DUMMY_HASH = bcrypt.hashpw(b"usuario-inexistente", bcrypt.gensalt()).decode()
_sesion_cache = TTLCache(maxsize=4000, ttl=10)


# ── Hashing de contraseñas ──────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Genera un hash bcrypt de la contraseña.

    bcrypt solo considera los primeros 72 bytes. Rechazamos contraseñas más
    largas en vez de truncarlas silenciosamente.
    """
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes en UTF-8")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica una contraseña contra su hash bcrypt."""
    try:
        raw = password.encode("utf-8")
        if len(raw) > 72:
            return False
        return bcrypt.checkpw(raw, password_hash.encode())
    except (ValueError, TypeError):
        return False


# ── JWT Tokens ──────────────────────────────────────────────────────────


def crear_token(user_id: int, username: str, rol: str, token_version: int = 0) -> str:
    """Genera un JWT firmado con los datos del usuario."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "rol": rol,
        "ver": int(token_version or 0),
        "exp": now + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verificar_token(token: str) -> dict | None:
    """Decodifica y valida un JWT. Retorna el payload con ``sub`` entero."""
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if "sub" in decoded:
            decoded["sub"] = int(decoded["sub"])
        return decoded
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, TypeError, ValueError):
        return None


# ── Operaciones de usuario ──────────────────────────────────────────────


def verificar_credenciales(username: str, password: str) -> dict | None:
    """Valida las credenciales y retorna los datos del usuario, o None.

    No captura errores de base de datos: el router los traduce a 503 para no
    ocultar una caída como si fueran credenciales inválidas.
    """
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id, username, password_hash, rol, consultas_max, "
                    "consultas_usadas, activo, COALESCE(token_version, 0) AS token_version "
                    "FROM usuarios WHERE username = :username"
                ),
                {"username": username},
            )
            .mappings()
            .first()
        )

    if not row:
        # Igualar el tiempo de respuesta para no filtrar qué usuarios existen.
        bcrypt.checkpw(password.encode("utf-8")[:72], _DUMMY_HASH.encode())
        return None

    user = dict(row)
    if not user["activo"]:
        bcrypt.checkpw(password.encode("utf-8")[:72], _DUMMY_HASH.encode())
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return user


def obtener_usuario_por_id(user_id: int) -> dict | None:
    """Obtiene un usuario por su ID."""
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id, username, rol, consultas_max, consultas_usadas, activo, "
                    "created_at, COALESCE(token_version, 0) AS token_version "
                    "FROM usuarios WHERE id = :id"
                ),
                {"id": user_id},
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


def validar_sesion(user_id: int, token_version: int) -> dict | None:
    """Valida que el usuario siga activo y que su token no haya sido revocado."""
    cache_key = f"{user_id}:{token_version}"
    cached = _sesion_cache.get(cache_key)
    if cached is not None:
        return cached

    user = obtener_usuario_por_id(user_id)
    if not user or not user["activo"] or int(user.get("token_version") or 0) != int(token_version):
        return None

    data = {
        "sub": user["id"],
        "username": user["username"],
        "rol": user["rol"],
        "ver": int(user.get("token_version") or 0),
    }
    _sesion_cache.set(cache_key, data)
    return data


def invalidar_cache_sesion(user_id: int | None = None) -> None:
    """Limpia la caché de sesiones (se llama al cambiar rol/estado/contraseña)."""
    if user_id is None:
        _sesion_cache.clear()
        return
    # La caché es pequeña; limpiar todo evita tener que indexar por usuario.
    _sesion_cache.clear()


def consumir_consulta(user_id: int, es_admin: bool = False) -> int | None:
    """Descuenta una consulta de forma atómica.

    Retorna el saldo restante, o ``None`` si no quedan consultas. Para admin
    retorna ``None`` y el llamador lo interpreta como ilimitado.
    """
    if es_admin:
        return None

    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                UPDATE usuarios
                SET consultas_usadas = consultas_usadas + 1
                WHERE id = :id
                  AND activo = true
                  AND consultas_usadas < consultas_max
                RETURNING consultas_max - consultas_usadas AS restantes
                """
                ),
                {"id": user_id},
            )
            .mappings()
            .first()
        )
        conn.commit()
        return int(row["restantes"]) if row else None


def reembolsar_consulta(user_id: int) -> None:
    """Devuelve una consulta cuando la operación no llegó a entregar datos."""
    try:
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE usuarios SET consultas_usadas = GREATEST(consultas_usadas - 1, 0) WHERE id = :id"),
                {"id": user_id},
            )
            conn.commit()
    except Exception:
        logger.exception("No se pudo reembolsar la consulta del usuario %s", user_id)


def consultas_restantes(user_id: int) -> int:
    """Retorna las consultas restantes del usuario."""
    user = obtener_usuario_por_id(user_id)
    if not user:
        return 0
    return max(0, user["consultas_max"] - user["consultas_usadas"])


def obtener_usuarios() -> list[dict]:
    """Lista todos los usuarios (para el admin)."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT id, username, rol, consultas_max, consultas_usadas, activo, "
                    "created_at, COALESCE(token_version, 0) AS token_version "
                    "FROM usuarios ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]


def crear_usuario(username: str, password: str, rol: str, consultas_max: int) -> dict | None:
    """Crea un nuevo usuario. Retorna sus datos o None si ya existe."""
    pw_hash = hash_password(password)
    try:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        """
                    INSERT INTO usuarios
                        (username, password_hash, rol, consultas_max, consultas_usadas, activo, token_version)
                    VALUES (:username, :password_hash, :rol, :consultas_max, 0, true, 0)
                    RETURNING id, username, rol, consultas_max, consultas_usadas, activo,
                              created_at, token_version
                    """
                    ),
                    {
                        "username": username,
                        "password_hash": pw_hash,
                        "rol": rol,
                        "consultas_max": consultas_max,
                    },
                )
                .mappings()
                .first()
            )
            conn.commit()
            return dict(row) if row else None
    except IntegrityError:
        return None


def actualizar_usuario(
    user_id: int,
    consultas_max: int | None = None,
    activo: bool | None = None,
    password: str | None = None,
) -> dict | None:
    """Actualiza campos de un usuario existente.

    Cambiar la contraseña o desactivar la cuenta incrementa ``token_version``
    para revocar los JWT emitidos anteriormente.
    """
    sets = []
    params: dict = {"id": user_id}

    if consultas_max is not None:
        sets.append("consultas_max = :consultas_max")
        params["consultas_max"] = consultas_max

    if activo is not None:
        sets.append("activo = :activo")
        params["activo"] = activo
        if not activo:
            sets.append("token_version = COALESCE(token_version, 0) + 1")

    if password is not None:
        sets.append("password_hash = :password_hash")
        params["password_hash"] = hash_password(password)
        sets.append("token_version = COALESCE(token_version, 0) + 1")

    if not sets:
        return obtener_usuario_por_id(user_id)

    query = (
        "UPDATE usuarios SET " + ", ".join(sets) + " WHERE id = :id RETURNING id, username, rol, consultas_max, "
        "consultas_usadas, activo, created_at, COALESCE(token_version, 0) AS token_version"
    )

    with engine.connect() as conn:
        row = conn.execute(text(query), params).mappings().first()
        conn.commit()
        invalidar_cache_sesion(user_id)
        return dict(row) if row else None


def eliminar_usuario(user_id: int) -> bool:
    """Elimina un usuario por su ID. No permite eliminar admins."""
    with engine.connect() as conn:
        result = conn.execute(
            text("DELETE FROM usuarios WHERE id = :id AND rol != 'admin' RETURNING id"),
            {"id": user_id},
        )
        conn.commit()
        invalidar_cache_sesion(user_id)
        return result.rowcount > 0


def asegurar_admin() -> None:
    """Crea el administrador inicial si la tabla no tiene ningún admin.

    Solo se ejecuta cuando ``ADMIN_PASSWORD`` está configurado. Nunca
    sobreescribe una cuenta existente: si ya hay un administrador, la función
    no hace nada.
    """
    if not ADMIN_PASSWORD:
        logger.warning("ADMIN_PASSWORD no configurado; no se creará un administrador inicial")
        return

    try:
        with engine.connect() as conn:
            existe = conn.execute(text("SELECT 1 FROM usuarios WHERE rol = 'admin' LIMIT 1")).first()
            if existe:
                return

            conn.execute(
                text(
                    """
                    INSERT INTO usuarios
                        (username, password_hash, rol, consultas_max, consultas_usadas,
                         activo, token_version)
                    VALUES (:username, :password_hash, 'admin', 1000000, 0, true, 0)
                    ON CONFLICT (username) DO NOTHING
                    """
                ),
                {
                    "username": ADMIN_USERNAME,
                    "password_hash": hash_password(ADMIN_PASSWORD),
                },
            )
            conn.commit()
            logger.info("Administrador inicial '%s' creado", ADMIN_USERNAME)
    except Exception:
        logger.exception("No se pudo crear el administrador inicial")
