import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine

logger = logging.getLogger(__name__)

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
                {"ip": ip, "tipo": tipo, "query": query[:500]},
            )
            conn.commit()
    except SQLAlchemyError:
        logger.exception("Error al registrar auditoría (ip=%s tipo=%s)", ip, tipo)
