from sqlalchemy import bindparam, text

from app.db import engine
from app.sql.queries import (
    BUCKET_SIZE,
    BUSCAR_BUCKETS,
    BUSCAR_DNI,
    BUSCAR_FONETICO,
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


def _precisos(conn, params, dnis: dict, limit: int, cand_limit: int = MAX_CANDIDATOS):
    top = sorted(dnis.items(), key=lambda kv: kv[1], reverse=True)[:cand_limit]
    ids = [dni for dni, _ in top]
    precise_params = {**params, "dni_list": ids}
    stmt = text(RANK_PRECISO).bindparams(bindparam("dni_list", expanding=True))
    return conn.execute(stmt, precise_params).mappings().all()


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
    # Escalar límites de candidatos dinámicamente:
    # 1 palabra requiere mayor amplitud de búsqueda en buckets
    cand_limit = MAX_CANDIDATOS * 2 if num_words == 1 else MAX_CANDIDATOS
    bucket_size = BUCKET_SIZE * 2 if num_words == 1 else BUCKET_SIZE

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
        "num_words_int": num_words,
        "cand_limit": cand_limit,
        "bucket_size": bucket_size,
    }
    with engine.connect() as conn:
        # SET LOCAL se revierte al finalizar la transacción del contexto
        conn.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.25"))
        conn.execute(text("SET LOCAL work_mem = '128MB'"))

        dnis = {}
        if num_words == 1:
            for bucket in BUSCAR_BUCKETS:
                _merge_candidatos(
                    conn.execute(text(bucket), params).mappings().all(), dnis
                )
            _merge_candidatos(conn.execute(text(BUSCAR_DNI), params).mappings().all(), dnis)
            if len(dnis) < cand_limit and w1:
                _merge_candidatos(
                    conn.execute(text(BUSCAR_FONETICO), params).mappings().all(), dnis
                )
        else:
            _merge_candidatos(
                conn.execute(text(BUSCAR_MULTIWORD), params).mappings().all(), dnis
            )

        # Fallback a trigramas si hay espacio en candidatos
        if len(dnis) < cand_limit:
            _merge_candidatos(
                conn.execute(text(BUSCAR_TYPO), params).mappings().all(), dnis
            )

        # Fallback fonético adicional para multi-palabra si aún hay espacio
        if num_words > 1 and len(dnis) < cand_limit and w1:
            _merge_candidatos(
                conn.execute(text(BUSCAR_FONETICO), params).mappings().all(), dnis
            )

        if not dnis:
            return []

        return _precisos(conn, params, dnis, limit, cand_limit=cand_limit)


def obtener_ruc_de_persona(dni: str):
    with engine.connect() as conn:
        return conn.execute(text(RUC_POR_DNI), {"dni": dni}).mappings().first()
