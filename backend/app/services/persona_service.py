"""Búsqueda de personas y acceso al árbol genealógico."""

from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy import bindparam, text

from app import config
from app.db import engine
from app.errors import QueryExecutionError
from app.sql.queries import (
    CANDIDATOS_DNI,
    CANDIDATOS_TSQUERY,
    PERSONA_POR_DNI,
    RANK_PRECISO,
    RUC_POR_DNI,
)

logger = logging.getLogger(__name__)


def obtener_por_dni(dni: str):
    with engine.connect() as conn:
        return conn.execute(text(PERSONA_POR_DNI), {"dni": dni}).mappings().first()


def obtener_ruc_de_persona(dni: str):
    with engine.connect() as conn:
        return conn.execute(text(RUC_POR_DNI), {"dni": dni}).mappings().first()


def _unaccent(valor: str) -> str:
    """Remueve acentos y diacríticos para búsquedas FTS precisas."""
    if not valor:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(valor))
    sin_comb = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sin_comb.replace("ñ", "n").replace("Ñ", "n")


def _sanitize_word(valor: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", _unaccent(valor)).strip().lower()


def _query_seguro(
    conn, sql: str, params: dict, *, timeout_ms: int = 2500, strict: bool = True
) -> list[dict]:
    """Consulta con timeout y savepoint para no abortar la transacción.

    Las consultas de generación de candidatos usan ``strict=False``: si una
    variante expira, se descarta y se continúa con las demás. El re-ranking
    final sí es estricto para no devolver un 200 vacío por un error de DB.
    """
    try:
        conn.execute(text("SAVEPOINT busqueda_query"))
        conn.execute(text(f"SET LOCAL statement_timeout = '{int(timeout_ms)}'"))
        filas = conn.execute(text(sql), params).mappings().all()
        conn.execute(text("RELEASE SAVEPOINT busqueda_query"))
        return [dict(f) for f in filas]
    except Exception as exc:
        # Los timeouts son parte del funcionamiento normal cuando los índices
        # opcionales no están creados; no hace falta volcar la traza completa.
        logger.warning("Consulta de búsqueda cancelada o fallida: %s", type(exc).__name__)
        try:
            conn.execute(text("ROLLBACK TO SAVEPOINT busqueda_query"))
            conn.execute(text("RELEASE SAVEPOINT busqueda_query"))
        except Exception:
            logger.debug("No se pudo liberar el savepoint de búsqueda", exc_info=True)
        if strict:
            raise QueryExecutionError("No se pudo ejecutar la búsqueda") from exc
        return []


def _agregar_dnis(destino: list[str], filas: list[dict], limite: int) -> None:
    for fila in filas:
        dni = fila.get("dni")
        if dni and dni not in destino:
            destino.append(dni)
            if len(destino) >= limite:
                return


def buscar_personas(
    q: str,
    q_lower: str,
    q_prefix: str,
    dni_prefix: str,
    num_words: int,
    limit: int,
    w1: str = "",
    w2: str = "",
    w3: str = "",
    w4: str = "",
):
    """Busca personas por nombre, apellido o DNI y re-rankea con precisión."""
    palabras = [_sanitize_word(w) for w in q_lower.split()]
    palabras = [p for p in palabras if p]
    if not palabras and not q.isdigit():
        return []

    limite_candidatos = config.BUSCAR_CANDIDATOS
    params = {
        "q": q,
        "q_lower": q_lower,
        "q_prefix": q_prefix,
        "dni_prefix": dni_prefix,
        "w1": w1,
        "w2": w2,
        "w3": w3,
        "w4": w4,
        "limit": limit,
        "num_words_int": len(palabras),
        "cand_limit": limite_candidatos,
    }

    with engine.connect() as conn:
        conn.execute(text("SET LOCAL work_mem = '64MB'"))
        dnis: list[str] = []
        es_dni = q.strip().isdigit()

        # 1. DNI exacto o prefijo. Si la consulta es puramente numérica no
        # tiene sentido buscar el número como si fuera un apellido o nombre.
        if any(c.isdigit() for c in q):
            _agregar_dnis(
                dnis,
                _query_seguro(conn, CANDIDATOS_DNI, params, timeout_ms=3000, strict=False),
                limite_candidatos,
            )

        # 2. Una sola palabra: el índice GIN de search_vector cubre tanto la
        # coincidencia exacta del token como su prefijo, y responde en
        # milisegundos sin depender de los índices B-Tree opcionales.
        if not es_dni and len(palabras) == 1 and len(dnis) < limite_candidatos:
            _agregar_dnis(
                dnis,
                _query_seguro(
                    conn,
                    CANDIDATOS_TSQUERY,
                    {"tsq": palabras[0], "cand_limit": limite_candidatos},
                    timeout_ms=3000,
                    strict=False,
                ),
                limite_candidatos,
            )
            if len(dnis) < limite_candidatos:
                _agregar_dnis(
                    dnis,
                    _query_seguro(
                        conn,
                        CANDIDATOS_TSQUERY,
                        {"tsq": f"{palabras[0]}:*", "cand_limit": limite_candidatos},
                        timeout_ms=3000,
                    ),
                    limite_candidatos,
                )

        # 3. Varias palabras: AND exacto, prefijo del último token y OR.
        # El OR se usa también cuando el AND devolvió pocos resultados para
        # no dejar fuera variantes razonables (nombres en otro orden, etc.).
        if not es_dni and len(palabras) >= 2 and len(dnis) < limite_candidatos:
            ts_and = " & ".join(palabras)
            _agregar_dnis(
                dnis,
                _query_seguro(
                    conn,
                    CANDIDATOS_TSQUERY,
                    {"tsq": ts_and, "cand_limit": limite_candidatos},
                    timeout_ms=5000,
                    strict=False,
                ),
                limite_candidatos,
            )
            if len(dnis) < limite_candidatos:
                ts_pref = " & ".join(palabras[:-1] + [f"{palabras[-1]}:*"])
                _agregar_dnis(
                    dnis,
                    _query_seguro(
                        conn,
                        CANDIDATOS_TSQUERY,
                        {"tsq": ts_pref, "cand_limit": limite_candidatos},
                        timeout_ms=5000,
                    ),
                    limite_candidatos,
                )
            if len(dnis) < limite_candidatos:
                ts_or = " | ".join(palabras)
                _agregar_dnis(
                    dnis,
                    _query_seguro(
                        conn,
                        CANDIDATOS_TSQUERY,
                        {"tsq": ts_or, "cand_limit": limite_candidatos},
                        timeout_ms=5000,
                    ),
                    limite_candidatos,
                )

        if not dnis:
            return []

        # El re-ranking se ejecuta sobre un conjunto pequeño; se amplía el
        # timeout para no cancelarlo por el límite usado en la generación.
        conn.execute(text("SET LOCAL statement_timeout = '15000'"))
        precise_params = {**params, "dni_list": dnis[:limite_candidatos]}
        stmt = text(RANK_PRECISO).bindparams(bindparam("dni_list", expanding=True))
        return conn.execute(stmt, precise_params).mappings().all()


def construir_arbol(dni: str, limite: int | None = None):
    """Delegación al motor familiar con confianza y evidencia."""
    from app.services.familia_service import construir_arbol as _construir

    return _construir(dni, limite)
