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
        "ubigeo_nac": fila.get("ubigeo_nac"),
        "ubigeo_dir": fila.get("ubigeo_dir"),
        "encontrado": True,
    }


def _nodo_solo_nombre(nombre_texto, sexo_hint=None):
    """Crea un nodo placeholder cuando solo se tiene el nombre de texto."""
    if not nombre_texto:
        return None
    partes = nombre_texto.strip().split()
    return {
        "dni": None,
        "nombres": " ".join(partes[:-2]) if len(partes) > 2 else (partes[0] if partes else nombre_texto),
        "ap_pat": partes[-2] if len(partes) >= 2 else None,
        "ap_mat": partes[-1] if len(partes) >= 2 else None,
        "sexo": sexo_hint,
        "edad_anios": None,
        "fecha_nac": None,
        "est_civil": None,
        "padre": None,
        "madre": None,
        "ubigeo_nac": None,
        "ubigeo_dir": None,
        "encontrado": False,
    }


def _build_tsq(*words) -> str:
    """Construye un tsquery seguro uniendo palabras con &."""
    clean = [_sanitize_word(w) for w in words if w and _sanitize_word(w)]
    return " & ".join(clean) if clean else ""


def _buscar_padre(conn, padre_nombre, hijo_fila):
    """Busca al padre usando ranking multi-factor con filtro GIN."""
    from app.sql.queries import BUSCAR_PADRE_RANKED

    padre_nombre_clean = padre_nombre.strip().lower()
    if not padre_nombre_clean:
        return None

    hijo_ap_pat = (hijo_fila.get("ap_pat") or "").lower()
    primer_nombre = padre_nombre_clean.split()[0] if padre_nombre_clean.split() else ""
    tsq = _build_tsq(primer_nombre, hijo_ap_pat)
    if not tsq:
        return None

    fecha_nac = hijo_fila.get("fecha_nac")
    params = {
        "tsq": tsq,
        "padre_nombre": padre_nombre_clean,
        "hijo_ap_pat": hijo_ap_pat,
        "hijo_ubigeo_nac": (hijo_fila.get("ubigeo_nac") or ""),
        "hijo_ubigeo_dir": (hijo_fila.get("ubigeo_dir") or ""),
        "hijo_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
    }

    try:
        fila = conn.execute(text(BUSCAR_PADRE_RANKED), params).mappings().first()
        return _fila_a_nodo(fila) if fila else None
    except Exception:
        return None


def _buscar_madre(conn, madre_nombre, hijo_fila):
    """Busca a la madre usando ranking multi-factor con filtro GIN."""
    from app.sql.queries import BUSCAR_MADRE_RANKED

    madre_nombre_clean = madre_nombre.strip().lower()
    if not madre_nombre_clean:
        return None

    hijo_ap_mat = (hijo_fila.get("ap_mat") or "").lower()
    primer_nombre = madre_nombre_clean.split()[0] if madre_nombre_clean.split() else ""
    tsq = _build_tsq(primer_nombre, hijo_ap_mat)
    if not tsq:
        return None

    fecha_nac = hijo_fila.get("fecha_nac")
    params = {
        "tsq": tsq,
        "madre_nombre": madre_nombre_clean,
        "hijo_ap_mat": hijo_ap_mat,
        "hijo_ubigeo_nac": (hijo_fila.get("ubigeo_nac") or ""),
        "hijo_ubigeo_dir": (hijo_fila.get("ubigeo_dir") or ""),
        "hijo_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
    }

    try:
        fila = conn.execute(text(BUSCAR_MADRE_RANKED), params).mappings().first()
        return _fila_a_nodo(fila) if fila else None
    except Exception:
        return None


def construir_arbol(dni: str):
    """Construye el árbol genealógico con ranking multi-factor y aceleración GIN.

    Factores de correlación:
    - Nombre de pila del padre/madre
    - Herencia de apellidos (ap_pat del padre → ap_pat del hijo, ap_pat de madre → ap_mat del hijo)
    - Ubigeo de nacimiento (distrito > provincia > departamento)
    - Ubigeo de domicilio
    - Rango de edad razonable entre generaciones
    - Sexo del candidato
    """
    from app.sql.queries import (
        BUSCAR_HERMANOS_RANKED,
        BUSCAR_HIJOS_RANKED,
        PERSONA_POR_DNI,
    )

    with engine.connect() as conn:
        # 1. Persona principal
        persona_fila = conn.execute(text(PERSONA_POR_DNI), {"dni": dni}).mappings().first()
        if not persona_fila:
            return None

        persona_nodo = _fila_a_nodo(persona_fila)

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
            padre_nodo = _buscar_padre(conn, padre_texto, persona_fila)
            if padre_nodo:
                resultado["padre"] = padre_nodo
                # Abuelos paternos
                abuelo_p_nombre = padre_nodo.get("padre")
                abuela_p_nombre = padre_nodo.get("madre")
                if abuelo_p_nombre and abuelo_p_nombre.strip():
                    abuelo = _buscar_padre(conn, abuelo_p_nombre, padre_nodo)
                    resultado["abuelo_paterno"] = abuelo or _nodo_solo_nombre(abuelo_p_nombre, "Masculino")
                if abuela_p_nombre and abuela_p_nombre.strip():
                    abuela = _buscar_madre(conn, abuela_p_nombre, padre_nodo)
                    resultado["abuela_paterna"] = abuela or _nodo_solo_nombre(abuela_p_nombre, "Femenino")
            else:
                resultado["padre"] = _nodo_solo_nombre(padre_texto, "Masculino")

        # 3. Buscar madre
        madre_texto = persona_fila.get("madre")
        if madre_texto and madre_texto.strip():
            madre_nodo = _buscar_madre(conn, madre_texto, persona_fila)
            if madre_nodo:
                resultado["madre"] = madre_nodo
                # Abuelos maternos
                abuelo_m_nombre = madre_nodo.get("padre")
                abuela_m_nombre = madre_nodo.get("madre")
                if abuelo_m_nombre and abuelo_m_nombre.strip():
                    abuelo = _buscar_padre(conn, abuelo_m_nombre, madre_nodo)
                    resultado["abuelo_materno"] = abuelo or _nodo_solo_nombre(abuelo_m_nombre, "Masculino")
                if abuela_m_nombre and abuela_m_nombre.strip():
                    abuela = _buscar_madre(conn, abuela_m_nombre, madre_nodo)
                    resultado["abuela_materna"] = abuela or _nodo_solo_nombre(abuela_m_nombre, "Femenino")
            else:
                resultado["madre"] = _nodo_solo_nombre(madre_texto, "Femenino")

        # 4. Buscar hermanos (mismos padres + apellidos + ubigeo + edad cercana)
        fecha_nac = persona_fila.get("fecha_nac")
        ap_pat_hijo = (persona_fila.get("ap_pat") or "").lower()
        ap_mat_hijo = (persona_fila.get("ap_mat") or "").lower()

        tsq_hermanos = _build_tsq(ap_pat_hijo, ap_mat_hijo) or _build_tsq(ap_pat_hijo)
        if tsq_hermanos:
            hermanos_filas = conn.execute(
                text(BUSCAR_HERMANOS_RANKED),
                {
                    "tsq": tsq_hermanos,
                    "dni_excluir": dni,
                    "padre": (padre_texto or "").strip().lower(),
                    "madre": (madre_texto or "").strip().lower(),
                    "hijo_ap_pat": ap_pat_hijo,
                    "hijo_ap_mat": ap_mat_hijo,
                    "hijo_ubigeo_nac": (persona_fila.get("ubigeo_nac") or ""),
                    "hijo_ubigeo_dir": (persona_fila.get("ubigeo_dir") or ""),
                    "hijo_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
                },
            ).mappings().all()
            resultado["hermanos"] = [_fila_a_nodo(h) for h in hermanos_filas]

        # 5. Buscar hijos
        nombres_persona = (persona_fila.get("nombres") or "").strip().lower()
        ap_pat_persona = ap_pat_hijo
        sexo_persona = str(persona_fila.get("sexo") or "")
        es_padre = sexo_persona in ("1", "Masculino")

        primer_nombre_persona = nombres_persona.split()[0] if nombres_persona.split() else ""
        tsq_hijos = _build_tsq(ap_pat_persona)

        conyuge_nombre = ""
        if es_padre and madre_texto:
            conyuge_nombre = madre_texto.strip().lower()
        elif not es_padre and padre_texto:
            conyuge_nombre = padre_texto.strip().lower()

        if tsq_hijos and primer_nombre_persona:
            hijos_filas = conn.execute(
                text(BUSCAR_HIJOS_RANKED),
                {
                    "tsq": tsq_hijos,
                    "progenitor_nombre": primer_nombre_persona,
                    "conyuge_nombre": conyuge_nombre,
                    "progenitor_ap_pat": ap_pat_persona,
                    "es_padre": es_padre,
                    "progenitor_ubigeo": (persona_fila.get("ubigeo_nac") or ""),
                    "progenitor_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
                },
            ).mappings().all()
            resultado["hijos"] = [_fila_a_nodo(h) for h in hijos_filas]

        return resultado



