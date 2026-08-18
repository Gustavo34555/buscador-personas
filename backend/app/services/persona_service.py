import re
from sqlalchemy import bindparam, text

from app.db import engine
from app.sql.queries import (
    CANDIDATOS_DNI,
    CANDIDATOS_TSQUERY,
    MAX_CANDIDATOS,
    PERSONA_POR_DNI,
    RANK_PRECISO,
    RUC_POR_DNI,
)


def obtener_por_dni(dni: str):
    with engine.connect() as conn:
        return conn.execute(text(PERSONA_POR_DNI), {"dni": dni}).mappings().first()


def _sanitize_word(w: str) -> str:
    return re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]", "", w).strip()


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
    clean_words = [_sanitize_word(w) for w in q_lower.split() if _sanitize_word(w)]
    if not clean_words and not q.isdigit():
        return []

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
        "num_words_int": len(clean_words),
        "cand_limit": MAX_CANDIDATOS,
    }

    with engine.connect() as conn:
        conn.execute(text("SET LOCAL work_mem = '64MB'"))

        dnis = []

        # 1. Si la búsqueda contiene dígitos o es DNI directo
        if any(c.isdigit() for c in q):
            dni_rows = conn.execute(text(CANDIDATOS_DNI), params).mappings().all()
            for r in dni_rows:
                dni = r.get("dni")
                if dni and dni not in dnis:
                    dnis.append(dni)

        # 2. Búsqueda por tokens GIN
        if len(clean_words) >= 1 and len(dnis) < MAX_CANDIDATOS:
            if len(clean_words) == 1:
                # Paso A: Palabra exacta
                ts_exact = clean_words[0]
                rows = conn.execute(
                    text(CANDIDATOS_TSQUERY),
                    {"tsq": ts_exact, "cand_limit": MAX_CANDIDATOS},
                ).mappings().all()
                for r in rows:
                    dni = r.get("dni")
                    if dni and dni not in dnis:
                        dnis.append(dni)

                # Paso B: Prefijo si faltan candidatos
                if len(dnis) < MAX_CANDIDATOS:
                    ts_pref = f"{clean_words[0]}:*"
                    rows = conn.execute(
                        text(CANDIDATOS_TSQUERY),
                        {"tsq": ts_pref, "cand_limit": MAX_CANDIDATOS},
                    ).mappings().all()
                    for r in rows:
                        dni = r.get("dni")
                        if dni and dni not in dnis:
                            dnis.append(dni)
            else:
                # Multi-palabra:
                # Paso A: Todos los tokens exactos (AND) -> máxima precisión y velocidad
                ts_and = " & ".join(clean_words)
                rows = conn.execute(
                    text(CANDIDATOS_TSQUERY),
                    {"tsq": ts_and, "cand_limit": MAX_CANDIDATOS},
                ).mappings().all()
                for r in rows:
                    dni = r.get("dni")
                    if dni and dni not in dnis:
                        dnis.append(dni)

                # Paso B: Prefijo en el último token (al autocompletar)
                if len(dnis) < limit:
                    ts_last_pref = " & ".join(clean_words[:-1] + [f"{clean_words[-1]}:*"])
                    rows = conn.execute(
                        text(CANDIDATOS_TSQUERY),
                        {"tsq": ts_last_pref, "cand_limit": MAX_CANDIDATOS},
                    ).mappings().all()
                    for r in rows:
                        dni = r.get("dni")
                        if dni and dni not in dnis:
                            dnis.append(dni)

                # Paso C: Fallback OR si aún no hay resultados (tolerancia a 1 término)
                if not dnis:
                    ts_or = " | ".join(clean_words)
                    rows = conn.execute(
                        text(CANDIDATOS_TSQUERY),
                        {"tsq": ts_or, "cand_limit": MAX_CANDIDATOS},
                    ).mappings().all()
                    for r in rows:
                        dni = r.get("dni")
                        if dni and dni not in dnis:
                            dnis.append(dni)

        if not dnis:
            return []

        # 3. Re-ranking de alta precisión sobre los candidatos seleccionados
        precise_params = {**params, "dni_list": dnis[:MAX_CANDIDATOS]}
        stmt = text(RANK_PRECISO).bindparams(bindparam("dni_list", expanding=True))
        return conn.execute(stmt, precise_params).mappings().all()


def obtener_ruc_de_persona(dni: str):
    with engine.connect() as conn:
        return conn.execute(text(RUC_POR_DNI), {"dni": dni}).mappings().first()
