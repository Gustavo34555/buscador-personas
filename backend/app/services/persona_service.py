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


def _nombre_completo(fila):
    """Construye nombre completo desde una fila de resultado."""
    partes = [fila.get("nombres"), fila.get("ap_pat"), fila.get("ap_mat")]
    return " ".join(p for p in partes if p).strip().lower()


def _fila_a_nodo(fila):
    """Convierte una fila de BD a diccionario de nodo del árbol."""
    return {
        "dni": fila.get("dni"),
        "nombres": fila.get("nombres"),
        "ap_pat": fila.get("ap_pat"),
        "ap_mat": fila.get("ap_mat"),
        "sexo": fila.get("sexo"),
        "edad_anios": fila.get("edad_anios"),
        "fecha_nac": str(fila["fecha_nac"]) if fila.get("fecha_nac") else None,
        "est_civil": fila.get("est_civil"),
        "padre": fila.get("padre"),
        "madre": fila.get("madre"),
        "encontrado": True,
    }


def _nodo_solo_nombre(nombre_texto, sexo_hint=None):
    """Crea un nodo placeholder cuando solo se tiene el nombre de texto."""
    if not nombre_texto:
        return None
    partes = nombre_texto.strip().split()
    return {
        "dni": None,
        "nombres": " ".join(partes[:-2]) if len(partes) > 2 else (partes[0] if partes else None),
        "ap_pat": partes[-2] if len(partes) >= 2 else None,
        "ap_mat": partes[-1] if len(partes) >= 2 else None,
        "sexo": sexo_hint,
        "edad_anios": None,
        "fecha_nac": None,
        "est_civil": None,
        "padre": None,
        "madre": None,
        "encontrado": False,
    }


def construir_arbol(dni: str):
    """Construye el árbol genealógico completo de una persona."""
    from app.sql.queries import (
        BUSCAR_HERMANOS,
        BUSCAR_HIJOS,
        BUSCAR_POR_NOMBRE_EXACTO,
        PERSONA_POR_DNI,
    )

    with engine.connect() as conn:
        # 1. Persona principal
        persona_fila = conn.execute(text(PERSONA_POR_DNI), {"dni": dni}).mappings().first()
        if not persona_fila:
            return None

        persona_nodo = _fila_a_nodo(persona_fila)
        nombre_persona = _nombre_completo(persona_fila)

        resultado = {
            "persona": persona_nodo,
            "padre": None,
            "madre": None,
            "abuelo_paterno": None,
            "abuela_paterna": None,
            "abuelo_materno": None,
            "abuela_materna": None,
            "hermanos": [],
            "hijos": [],
        }

        # 2. Buscar padre
        padre_texto = persona_fila.get("padre")
        if padre_texto and padre_texto.strip():
            padre_filas = conn.execute(
                text(BUSCAR_POR_NOMBRE_EXACTO),
                {"nombre_completo": padre_texto.strip().lower()},
            ).mappings().all()
            if padre_filas:
                resultado["padre"] = _fila_a_nodo(padre_filas[0])
                # Abuelos paternos
                abuelo_p = padre_filas[0].get("padre")
                abuela_p = padre_filas[0].get("madre")
                if abuelo_p and abuelo_p.strip():
                    ab_filas = conn.execute(
                        text(BUSCAR_POR_NOMBRE_EXACTO),
                        {"nombre_completo": abuelo_p.strip().lower()},
                    ).mappings().all()
                    resultado["abuelo_paterno"] = _fila_a_nodo(ab_filas[0]) if ab_filas else _nodo_solo_nombre(abuelo_p, "Masculino")
                if abuela_p and abuela_p.strip():
                    ab_filas = conn.execute(
                        text(BUSCAR_POR_NOMBRE_EXACTO),
                        {"nombre_completo": abuela_p.strip().lower()},
                    ).mappings().all()
                    resultado["abuela_paterna"] = _fila_a_nodo(ab_filas[0]) if ab_filas else _nodo_solo_nombre(abuela_p, "Femenino")
            else:
                resultado["padre"] = _nodo_solo_nombre(padre_texto, "Masculino")

        # 3. Buscar madre
        madre_texto = persona_fila.get("madre")
        if madre_texto and madre_texto.strip():
            madre_filas = conn.execute(
                text(BUSCAR_POR_NOMBRE_EXACTO),
                {"nombre_completo": madre_texto.strip().lower()},
            ).mappings().all()
            if madre_filas:
                resultado["madre"] = _fila_a_nodo(madre_filas[0])
                # Abuelos maternos
                abuelo_m = madre_filas[0].get("padre")
                abuela_m = madre_filas[0].get("madre")
                if abuelo_m and abuelo_m.strip():
                    ab_filas = conn.execute(
                        text(BUSCAR_POR_NOMBRE_EXACTO),
                        {"nombre_completo": abuelo_m.strip().lower()},
                    ).mappings().all()
                    resultado["abuelo_materno"] = _fila_a_nodo(ab_filas[0]) if ab_filas else _nodo_solo_nombre(abuelo_m, "Masculino")
                if abuela_m and abuela_m.strip():
                    ab_filas = conn.execute(
                        text(BUSCAR_POR_NOMBRE_EXACTO),
                        {"nombre_completo": abuela_m.strip().lower()},
                    ).mappings().all()
                    resultado["abuela_materna"] = _fila_a_nodo(ab_filas[0]) if ab_filas else _nodo_solo_nombre(abuela_m, "Femenino")
            else:
                resultado["madre"] = _nodo_solo_nombre(madre_texto, "Femenino")

        # 4. Buscar hermanos (mismos padres)
        if (padre_texto and padre_texto.strip()) or (madre_texto and madre_texto.strip()):
            hermanos_filas = conn.execute(
                text(BUSCAR_HERMANOS),
                {
                    "dni_excluir": dni,
                    "padre": (padre_texto or "").strip(),
                    "madre": (madre_texto or "").strip(),
                },
            ).mappings().all()
            resultado["hermanos"] = [_fila_a_nodo(h) for h in hermanos_filas]

        # 5. Buscar hijos
        if nombre_persona:
            hijos_filas = conn.execute(
                text(BUSCAR_HIJOS),
                {"nombre_completo": nombre_persona},
            ).mappings().all()
            resultado["hijos"] = [_fila_a_nodo(h) for h in hijos_filas]

        return resultado

