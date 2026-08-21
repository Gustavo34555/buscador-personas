from datetime import date, datetime
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
    sexo: str | None = None,
    edad_min: int | None = None,
    edad_max: int | None = None,
    departamento: str | None = None,
    est_civil: str | None = None,
):
    clean_words = [_sanitize_word(w) for w in q_lower.split() if _sanitize_word(w)]
    if not clean_words and not q.isdigit():
        return []

    # Normalizar filtro de sexo a 'M', 'F' o None
    filtro_sexo = None
    if sexo:
        s_norm = str(sexo).strip().upper()
        if s_norm in ("M", "MASCULINO", "1"):
            filtro_sexo = "M"
        elif s_norm in ("F", "FEMENINO", "2"):
            filtro_sexo = "F"

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
        "filtro_sexo": filtro_sexo,
        "edad_min": edad_min,
        "edad_max": edad_max,
        "departamento": departamento.strip() if departamento else None,
        "est_civil": est_civil.strip() if est_civil else None,
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
                    {**params, "tsq": ts_exact},
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
                        {**params, "tsq": ts_pref},
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
                    {**params, "tsq": ts_and},
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
                        {**params, "tsq": ts_last_pref},
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
                        {**params, "tsq": ts_or},
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


def _parse_date(d):
    """Parsea una fecha de string o date a objeto datetime.date."""
    if not d:
        return None
    if isinstance(d, date):
        return d
    try:
        from datetime import datetime
        return datetime.strptime(str(d).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _es_edad_progenitor_valida(fecha_progenitor, fecha_descendiente, min_dif=13, max_dif=75) -> bool:
    """Valida biológicamente que un progenitor sea mayor que su descendiente."""
    d_prog = _parse_date(fecha_progenitor)
    d_desc = _parse_date(fecha_descendiente)
    if not d_prog or not d_desc:
        return True  # Sin fecha registrada, no se puede descartar por edad
    if d_prog >= d_desc:
        return False  # Progenitor nació después o igual que el descendiente -> IMPOSIBLE
    dif_anios = (d_desc - d_prog).days / 365.25
    return min_dif <= dif_anios <= max_dif


def _es_edad_hijo_valida(fecha_hijo, fecha_progenitor, min_dif=13, max_dif=70) -> bool:
    """Valida que un hijo haya nacido después de su progenitor."""
    return _es_edad_progenitor_valida(fecha_progenitor, fecha_hijo, min_dif=min_dif, max_dif=max_dif)


def _es_nombre_progenitor_compatible(nombre_registrado_hijo: str, nombres_progenitor: str, ap_pat: str = "", ap_mat: str = "") -> bool:
    """Verifica que el nombre registrado en padre/madre no contenga nombres conflictivos ajenos.

    Por ejemplo, si la madre es 'JAQUELIN MILEYDI' y el hijo tiene madre 'JAQUELIN DIANA',
    el token 'DIANA' es un nombre ajeno y se descarta inmediatamente como homónimo.
    """
    if not nombre_registrado_hijo or not nombres_progenitor:
        return False

    tokens_registrados = [t.strip().lower() for t in nombre_registrado_hijo.split() if t.strip()]
    tokens_validos = set(
        [t.strip().lower() for t in (nombres_progenitor + " " + ap_pat + " " + ap_mat).split() if t.strip()]
    )
    return all(t in tokens_validos for t in tokens_registrados)


def _es_edad_pareja_coherente(fecha_1, fecha_2, max_dif=25) -> bool:
    """Valida que la diferencia de edad entre cónyuges/pareja sea biológicamente razonable (<= 25 años)."""
    d1 = _parse_date(fecha_1)
    d2 = _parse_date(fecha_2)
    if not d1 or not d2:
        return True
    return abs((d1 - d2).days / 365.25) <= max_dif


def _buscar_pareja_en_bd(conn, nombres_pareja, ap_pat_pareja, titular_fila, es_padre_titular):
    """Busca en la base de datos a la pareja (madre o padre) para validar la relación familiar."""
    primer_nombre = _sanitize_word(nombres_pareja.split()[0]) if nombres_pareja.split() else ""
    ap_pat_clean = _sanitize_word(ap_pat_pareja)
    if not primer_nombre or not ap_pat_clean:
        return None

    tsq = f"{ap_pat_clean} & {primer_nombre}"
    ubigeo_nac = titular_fila.get("ubigeo_nac") or ""
    fecha_nac_titular = titular_fila.get("fecha_nac")

    query = """
        SELECT dni, ap_pat, ap_mat, nombres, fecha_nac, ubigeo_nac, ubigeo_dir, direccion
        FROM personas
        WHERE search_vector @@ to_tsquery('simple', :tsq)
          AND lower(ap_pat) = :ap_pat
          AND (lower(nombres) = :nombres OR lower(nombres) LIKE :primer_nom || ' %')
          AND (:ubigeo_nac = '' OR ubigeo_nac = :ubigeo_nac OR SUBSTRING(ubigeo_nac, 1, 4) = SUBSTRING(:ubigeo_nac, 1, 4))
        LIMIT 5;
    """
    try:
        filas = conn.execute(text(query), {
            "tsq": tsq,
            "ap_pat": ap_pat_clean.lower(),
            "nombres": nombres_pareja.strip().lower(),
            "primer_nom": primer_nombre.lower(),
            "ubigeo_nac": ubigeo_nac,
        }).mappings().all()

        for f in filas:
            if _es_edad_pareja_coherente(f.get("fecha_nac"), fecha_nac_titular):
                return dict(f)
    except Exception:
        pass
    return None


def _build_tsq(*words) -> str:
    """Construye un tsquery seguro uniendo palabras con &."""
    clean = [_sanitize_word(w) for w in words if w and _sanitize_word(w)]
    return " & ".join(clean) if clean else ""


def _buscar_padre(conn, padre_nombre, hijo_fila):
    """Busca al padre usando ranking multi-factor con filtro GIN y validación biológica."""
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
        "hijo_direccion": (hijo_fila.get("direccion") or "").strip().lower(),
        "hijo_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
    }

    try:
        fila = conn.execute(text(BUSCAR_PADRE_RANKED), params).mappings().first()
        if fila and _es_edad_progenitor_valida(fila.get("fecha_nac"), fecha_nac):
            return _fila_a_nodo(fila)
        return None
    except Exception:
        return None


def _buscar_madre(conn, madre_nombre, hijo_fila):
    """Busca a la madre usando ranking multi-factor con filtro GIN y validación biológica."""
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
        "hijo_direccion": (hijo_fila.get("direccion") or "").strip().lower(),
        "hijo_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
    }

    try:
        fila = conn.execute(text(BUSCAR_MADRE_RANKED), params).mappings().first()
        if fila and _es_edad_progenitor_valida(fila.get("fecha_nac"), fecha_nac, min_dif=13, max_dif=55):
            return _fila_a_nodo(fila)
        return None
    except Exception:
        return None


def construir_arbol(dni: str):
    """Construye el árbol genealógico con lógica biológica estricta y aceleración GIN.

    Factores de correlación y validación:
    - Regla biológica estricta: progenitores > descendientes (mínimo 13 años de diferencia)
    - Nombre de pila del padre/madre
    - Herencia de apellidos (ap_pat del padre → ap_pat del hijo, ap_pat de madre → ap_mat del hijo)
    - Correlación geográfica por Ubigeo de nacimiento y domicilio
    - Correlación de dirección física exacta
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
        fecha_nac_persona = persona_fila.get("fecha_nac")

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
                # Abuelos paternos (validados respecto a la edad del padre)
                abuelo_p_nombre = padre_nodo.get("padre")
                abuela_p_nombre = padre_nodo.get("madre")
                if abuelo_p_nombre and abuelo_p_nombre.strip():
                    abuelo = _buscar_padre(conn, abuelo_p_nombre, padre_nodo)
                    if abuelo and _es_edad_progenitor_valida(abuelo.get("fecha_nac"), padre_nodo.get("fecha_nac")):
                        resultado["abuelo_paterno"] = abuelo
                    else:
                        resultado["abuelo_paterno"] = _nodo_solo_nombre(abuelo_p_nombre, "Masculino")
                if abuela_p_nombre and abuela_p_nombre.strip():
                    abuela = _buscar_madre(conn, abuela_p_nombre, padre_nodo)
                    if abuela and _es_edad_progenitor_valida(abuela.get("fecha_nac"), padre_nodo.get("fecha_nac")):
                        resultado["abuela_paterna"] = abuela
                    else:
                        resultado["abuela_paterna"] = _nodo_solo_nombre(abuela_p_nombre, "Femenino")
            else:
                resultado["padre"] = _nodo_solo_nombre(padre_texto, "Masculino")

        # 3. Buscar madre
        madre_texto = persona_fila.get("madre")
        if madre_texto and madre_texto.strip():
            madre_nodo = _buscar_madre(conn, madre_texto, persona_fila)
            if madre_nodo:
                resultado["madre"] = madre_nodo
                # Abuelos maternos (validados respecto a la edad de la madre)
                abuelo_m_nombre = madre_nodo.get("padre")
                abuela_m_nombre = madre_nodo.get("madre")
                if abuelo_m_nombre and abuelo_m_nombre.strip():
                    abuelo = _buscar_padre(conn, abuelo_m_nombre, madre_nodo)
                    if abuelo and _es_edad_progenitor_valida(abuelo.get("fecha_nac"), madre_nodo.get("fecha_nac")):
                        resultado["abuelo_materno"] = abuelo
                    else:
                        resultado["abuelo_materno"] = _nodo_solo_nombre(abuelo_m_nombre, "Masculino")
                if abuela_m_nombre and abuela_m_nombre.strip():
                    abuela = _buscar_madre(conn, abuela_m_nombre, madre_nodo)
                    if abuela and _es_edad_progenitor_valida(abuela.get("fecha_nac"), madre_nodo.get("fecha_nac")):
                        resultado["abuela_materna"] = abuela
                    else:
                        resultado["abuela_materna"] = _nodo_solo_nombre(abuela_m_nombre, "Femenino")
            else:
                resultado["madre"] = _nodo_solo_nombre(madre_texto, "Femenino")

        # 4. Buscar hermanos (mismo padre + apellidos + ubigeo + dirección + edad cercana)
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
                    "hijo_direccion": (persona_fila.get("direccion") or "").strip().lower(),
                    "hijo_fecha_nac": str(fecha_nac_persona) if fecha_nac_persona else "1900-01-01",
                },
            ).mappings().all()
            resultado["hermanos"] = [_fila_a_nodo(h) for h in hermanos_filas]

        # 5. Buscar hijos: cruce integral de datos compartidos (nombre progenitor, apellidos, ubigeos, dirección, edad)
        nombres_persona = (persona_fila.get("nombres") or "").strip().lower()
        ap_pat_persona = ap_pat_hijo
        ap_mat_persona = ap_mat_hijo
        sexo_persona = str(persona_fila.get("sexo") or "")
        es_padre = sexo_persona in ("1", "Masculino")

        primer_nombre_persona = nombres_persona.split()[0] if nombres_persona.split() else ""
        
        # El apellido heredado está presente en el search_vector del hijo
        tsq_hijos = _build_tsq(ap_pat_persona)

        # Solo buscar hijos si se conoce la fecha de nacimiento y la persona tiene edad suficiente
        d_persona = _parse_date(fecha_nac_persona)
        puede_tener_hijos = d_persona is not None and (date.today() - d_persona).days / 365.25 >= 13

        if tsq_hijos and primer_nombre_persona and puede_tener_hijos:
            hijos_filas = conn.execute(
                text(BUSCAR_HIJOS_RANKED),
                {
                    "tsq": tsq_hijos,
                    "progenitor_dni": dni,
                    "progenitor_nombre": primer_nombre_persona,
                    "progenitor_nombre_completo": nombres_persona,
                    "progenitor_ap_pat": ap_pat_persona,
                    "progenitor_ap_mat": ap_mat_persona,
                    "es_padre": es_padre,
                    "progenitor_ubigeo_nac": (persona_fila.get("ubigeo_nac") or ""),
                    "progenitor_ubigeo_dir": (persona_fila.get("ubigeo_dir") or ""),
                    "progenitor_direccion": (persona_fila.get("direccion") or "").strip().lower(),
                    "progenitor_fecha_nac": str(fecha_nac_persona),
                },
            ).mappings().all()

            campo_progenitor = "padre" if es_padre else "madre"
            hijos_candidatos = [
                dict(h) for h in hijos_filas
                if _es_edad_hijo_valida(h.get("fecha_nac"), fecha_nac_persona)
                and _es_nombre_progenitor_compatible(
                    h.get(campo_progenitor),
                    nombres_persona,
                    ap_pat_persona,
                    ap_mat_persona
                )
            ]

            # ══════════════════════════════════════════════════════════════════
            # TRIANGULACIÓN Y CORRELACIÓN ESTRICTA PADRE-MADRE-HIJO
            # ══════════════════════════════════════════════════════════════════
            if hijos_candidatos:
                # 1. Agrupar candidatos por la unidad parental de la otra rama:
                #    Si el titular es PADRE -> agrupar por (madre_nombre, ap_mat)
                #    Si el titular es MADRE -> agrupar por (padre_nombre, ap_pat)
                campo_pareja_nombre = "madre" if es_padre else "padre"
                campo_pareja_apellido = "ap_mat" if es_padre else "ap_pat"

                dir_padre = (persona_fila.get("direccion") or "").strip().lower()
                ubigeo_nac_padre = persona_fila.get("ubigeo_nac") or ""
                ubigeo_dir_padre = persona_fila.get("ubigeo_dir") or ""

                from collections import defaultdict
                familias_por_pareja = defaultdict(list)
                pareja_validada_cache = {}

                for h in hijos_candidatos:
                    nom_pareja = (h.get(campo_pareja_nombre) or "").strip().lower()
                    ap_pareja = (h.get(campo_pareja_apellido) or "").strip().lower()
                    clave_pareja = (nom_pareja, ap_pareja)
                    familias_por_pareja[clave_pareja].append(h)

                # 2. Evaluar y calificar cada relación de pareja (Padre + Madre)
                hijos_calificados = []
                for (nom_pareja, ap_pareja), lista_hijos in familias_por_pareja.items():
                    # Verificar si la pareja existe en la BD en la misma zona
                    pareja_bd = None
                    if nom_pareja and ap_pareja:
                        clave_str = f"{nom_pareja}:{ap_pareja}"
                        if clave_str not in pareja_validada_cache:
                            pareja_validada_cache[clave_str] = _buscar_pareja_en_bd(
                                conn, nom_pareja, ap_pareja, persona_fila, es_padre
                            )
                        pareja_bd = pareja_validada_cache[clave_str]

                    # Calcular afinidad global de esta unidad familiar
                    afinidad_pareja = 0
                    if pareja_bd:
                        # Pareja confirmada en BD con misma geolocalización (+8000)
                        afinidad_pareja += 8000
                    
                    # Número de hijos compartidos en la misma unión (+2000 por cada hermano)
                    if len(lista_hijos) > 1:
                        afinidad_pareja += min(len(lista_hijos) * 2000, 6000)

                    for h in lista_hijos:
                        bonus = afinidad_pareja
                        # A. Mismo distrito de nacimiento (+3000)
                        if ubigeo_nac_padre and h.get("ubigeo_nac") == ubigeo_nac_padre:
                            bonus += 3000
                        # B. Mismo distrito de domicilio (+2500)
                        if ubigeo_dir_padre and h.get("ubigeo_dir") == ubigeo_dir_padre:
                            bonus += 2500
                        # C. Misma dirección o localidad compartida (+3500)
                        dir_hijo = (h.get("direccion") or "").strip().lower()
                        if dir_padre and dir_hijo and (dir_padre == dir_hijo or dir_padre in dir_hijo or dir_hijo in dir_padre):
                            bonus += 3500

                        h["score_total"] = (h.get("score") or 0) + bonus
                        hijos_calificados.append(h)

                # 3. Filtrar clúster con la mayor cantidad de datos compartidos y relación padre-madre
                if hijos_calificados:
                    max_score_total = max(h["score_total"] for h in hijos_calificados)
                    
                    # Umbral estricto: Solo aceptar candidatos que demuestren correlación padre-madre
                    # o fuerte arraigo geográfico/habitacional compartido (score_total >= 25000)
                    if max_score_total >= 32000:
                        hijos_filtrados = [
                            h for h in hijos_calificados
                            if h["score_total"] >= max_score_total - 6000 and h["score_total"] >= 25000
                        ]
                    elif max_score_total >= 25000:
                        hijos_filtrados = [
                            h for h in hijos_calificados
                            if h["score_total"] >= max_score_total - 4000 and h["score_total"] >= 25000
                        ]
                    else:
                        hijos_filtrados = []

                    # 4. Ordenar cronológicamente (de mayor a menor por fecha de nacimiento)
                    hijos_filtrados.sort(
                        key=lambda x: str(x.get("fecha_nac") or "1900-01-01")
                    )

                    resultado["hijos"] = [_fila_a_nodo(h) for h in hijos_filtrados]

        return resultado




