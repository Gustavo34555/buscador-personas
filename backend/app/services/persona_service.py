from sqlalchemy import bindparam, text

from app.db import engine
from app.sql.queries import (
    BUCKET_SIZE,
    BUSCAR_BUCKETS,
    BUSCAR_DNI,
    BUSCAR_MULTIWORD,
    BUSCAR_TYPO,
    MAX_CANDIDATOS,
    PERSONA_POR_DNI,
    RANK_PRECISO,
    RUC_POR_DNI,
)


def obtener_por_dni(dni: str):
    with engine.connect() as conn:
        return conn.execute(text(PERSONA_POR_DNI), {"dni": dni}).mappings().first()


def _merge_candidatos(rows, dnis: dict) -> dict:
    for fila in rows:
        dnis.setdefault(fila["dni"], fila.get("pre_rank") or 0)
    return dnis


def _precisos(conn, params, dnis: dict, limit: int):
    top = sorted(dnis.items(), key=lambda kv: kv[1], reverse=True)[:MAX_CANDIDATOS]
    ids = [dni for dni, _ in top]
    precise_params = {**params, "dni_list": ids}
    stmt = text(RANK_PRECISO).bindparams(bindparam("dni_list", expanding=True))
    return conn.execute(stmt, precise_params).mappings().all()


def buscar_personas(q, q_lower, q_prefix, dni_prefix, num_words: int, limit: int):
    params = {
        "q": q,
        "q_lower": q_lower,
        "q_prefix": q_prefix,
        "dni_prefix": dni_prefix,
        "limit": limit,
        "num_words_int": num_words,
        "cand_limit": MAX_CANDIDATOS,
        "bucket_size": BUCKET_SIZE,
    }
    with engine.connect() as conn:
        # SET LOCAL se revierte al finalizar la transaccion del contexto
        conn.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.25"))
        conn.execute(text("SET LOCAL work_mem = '128MB'"))

        dnis = {}
        if num_words == 1:
            for bucket in BUSCAR_BUCKETS:
                _merge_candidatos(
                    conn.execute(text(bucket), params).mappings().all(), dnis
                )
            _merge_candidatos(conn.execute(text(BUSCAR_DNI), params).mappings().all(), dnis)
        else:
            _merge_candidatos(
                conn.execute(text(BUSCAR_MULTIWORD), params).mappings().all(), dnis
            )
        if len(dnis) < MAX_CANDIDATOS:
            _merge_candidatos(
                conn.execute(text(BUSCAR_TYPO), params).mappings().all(), dnis
            )
        if not dnis:
            return []

        return _precisos(conn, params, dnis, limit)


def obtener_ruc_de_persona(dni: str):
    with engine.connect() as conn:
        return conn.execute(text(RUC_POR_DNI), {"dni": dni}).mappings().first()
