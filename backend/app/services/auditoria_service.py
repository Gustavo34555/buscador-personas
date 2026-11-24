from __future__ import annotations

import hashlib
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine

logger = logging.getLogger(__name__)


def _hash_query(query: str) -> str:
    """Guarda una huella, no el texto: la búsqueda puede contener PII."""
    return "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()[:40]


INSERT_AUDITORIA = """
    INSERT INTO auditoria_consultas (ip, tipo, query)
    VALUES (:ip, :tipo, :query)
"""


def registrar(ip: str, tipo: str, query: str) -> None:
    """Registra una consulta. Nunca debe romper la petición original."""
    try:
        with engine.connect() as conn:
            conn.execute(
                text(INSERT_AUDITORIA),
                {"ip": ip, "tipo": tipo, "query": _hash_query(query)},
            )
            conn.commit()
    except SQLAlchemyError:
        logger.exception("Error al registrar auditoría (ip=%s tipo=%s)", ip, tipo)
