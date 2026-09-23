from datetime import date, datetime, timedelta
import logging
import re
from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)

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


import unicodedata

def _unaccent(s: str) -> str:
    """Remueve acentos, diacríticos y normaliza la letra eñe para búsquedas FTS precisas."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    no_comb = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_comb.replace("ñ", "n").replace("Ñ", "n")


def _sanitize_word(w: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", _unaccent(w)).strip()


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


def _tokens_campo(texto: str) -> list[str]:
    """Tokeniza un campo padre/madre: sin acentos, minúsculas, solo alfanumérico."""
    return [
        tok
        for tok in (_sanitize_word(w).lower() for w in _unaccent(texto or "").split())
        if tok
    ]


def _split_pares(pares: list[tuple[str, str]], apellido_ref: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Núcleo común de separación: recibe pares (texto_original, token_limpio)
    y devuelve (pares_nombres, pares_apellidos)."""
    tokens = [t for _, t in pares]
    ap = _sanitize_word(apellido_ref or "").lower()
    if ap and ap in tokens:
        i = tokens.index(ap)
        if i == 0:
            # Formato 'APELLIDOS NOMBRES'
            corte = 2 if len(pares) > 2 else 1
            return pares[corte:], pares[:corte]
        # Formato 'NOMBRES APELLIDOS'
        return pares[:i], pares[i:]
    # Apellido de referencia ausente: el campo solo trae nombres de pila
    return pares, []


def _separar_nombres_apellidos(tokens: list[str], apellido_ref: str) -> tuple[list[str], list[str]]:
    """Separa los tokens de un campo padre/madre en (nombres, apellidos).

    Usa la posición del apellido heredado (ap_pat del hijo para el padre,
    ap_mat del hijo para la madre) para detectar el formato del texto:
    - 'NOMBRES APELLIDOS'  (apellido de referencia al final)  → formato peruano común
    - 'APELLIDOS NOMBRES'  (apellido de referencia al inicio)
    - Si el apellido no aparece, se asume que el campo solo trae nombres de pila.

    Evita el bug histórico de tratar apellidos como segundo nombre (lo que
    aplicaba penalizaciones erróneas de -8000 a candidatos correctos).
    """
    pares = [(t, t) for t in tokens]
    nombres, apellidos = _split_pares(pares, apellido_ref)
    return [p for p, _ in nombres], [p for p, _ in apellidos]


def _fila_a_nodo(fila):
    """Convierte una fila de BD a diccionario de nodo del árbol."""
    edad = fila.get("edad_anios")
    fn = fila.get("fecha_nac")
    if edad is None and fn:
        d = _parse_date(fn)
        if d:
            today = date.today()
            edad = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return {
        "dni": fila.get("dni"),
        "nombres": fila.get("nombres"),
        "ap_pat": fila.get("ap_pat"),
        "ap_mat": fila.get("ap_mat"),
        "sexo": fila.get("sexo"),
        "edad_anios": edad,
        "fecha_nac": str(fn) if fn else None,
        "est_civil": fila.get("est_civil"),
        "padre": fila.get("padre"),
        "madre": fila.get("madre"),
        "direccion": fila.get("direccion"),
        "ubigeo_nac": fila.get("ubigeo_nac"),
        "ubigeo_dir": fila.get("ubigeo_dir"),
        "encontrado": True,
    }


def _nodo_solo_nombre(nombre_texto, sexo_hint=None, apellido_ref=None):
    """Crea un nodo placeholder cuando solo se tiene el nombre de texto.

    Usa `apellido_ref` (apellido heredado conocido) para separar nombres de
    apellidos con el mismo criterio que `_separar_nombres_apellidos`.
    """
    if not nombre_texto:
        return None
    # Mantener capitalización original para mostrar, pero parsear con tokens limpios
    pares = [
        (p, _sanitize_word(p).lower())
        for p in str(nombre_texto).strip().split()
    ]
    pares = [(p, t) for p, t in pares if t]
    if not pares:
        return None
    nombres_p, apellidos_p = _split_pares(pares, apellido_ref or "")
    if not nombres_p:  # el texto solo traía apellidos
        nombres_p, apellidos_p = pares, []
    return {
        "dni": None,
        "nombres": " ".join(p for p, _ in nombres_p),
        "ap_pat": apellidos_p[0][0] if apellidos_p else None,
        "ap_mat": apellidos_p[1][0] if len(apellidos_p) > 1 else None,
        "sexo": sexo_hint,
        "edad_anios": None,
        "fecha_nac": None,
        "est_civil": None,
        "padre": None,
        "madre": None,
        "direccion": None,
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

    También detecta conflictos de segundo nombre: si el hijo registra 2+ nombres y el
    progenitor tiene 2+ nombres de pila, verifica que no haya un segundo nombre ajeno
    (ej: registrado='CARLOS EDUARDO', progenitor nombres='CARLOS ENRIQUE' → incompatible).
    """
    if not nombre_registrado_hijo or not nombres_progenitor:
        return False

    tokens_registrados = [t.strip().lower() for t in nombre_registrado_hijo.split() if t.strip()]
    tokens_validos = set(
        [t.strip().lower() for t in (nombres_progenitor + " " + ap_pat + " " + ap_mat).split() if t.strip()]
    )
    if not all(t in tokens_validos for t in tokens_registrados):
        return False

    # Detección de segundo nombre conflictivo
    if len(tokens_registrados) >= 2:
        nombres_pila_prog = [t.strip().lower() for t in nombres_progenitor.split() if t.strip()]
        if len(nombres_pila_prog) >= 2:
            segundo_registrado = tokens_registrados[1]
            # Si el segundo token NO es un nombre del progenitor ni un apellido → ajeno
            if (segundo_registrado not in [t.lower() for t in nombres_pila_prog]
                    and segundo_registrado != ap_pat.strip().lower()
                    and segundo_registrado != ap_mat.strip().lower()):
                return False

    return True


def _es_edad_pareja_coherente(fecha_1, fecha_2, max_dif=25) -> bool:
    """Valida que la diferencia de edad entre cónyuges/pareja sea biológicamente razonable (<= 25 años)."""
    d1 = _parse_date(fecha_1)
    d2 = _parse_date(fecha_2)
    if not d1 or not d2:
        return True
    return abs((d1 - d2).days / 365.25) <= max_dif


def _normalizar_direccion(dir_str):
    """Normaliza una dirección para comparación flexible de tokens."""
    if not dir_str:
        return ""
    d = _unaccent(dir_str).lower()
    # Normalizar abreviaciones comunes peruanas
    d = re.sub(r'\bmz\.?\s*', 'mz ', d)
    d = re.sub(r'\bmza\.?\s*', 'mz ', d)
    d = re.sub(r'\bmanzana\s+', 'mz ', d)
    d = re.sub(r'\blt\.?\s*', 'lt ', d)
    d = re.sub(r'\blote\s+', 'lt ', d)
    d = re.sub(r'\basent\.?\s*h\.?\s*', '', d)
    d = re.sub(r'\bav\.?\s*', 'av ', d)
    d = re.sub(r'\bavenida\s+', 'av ', d)
    d = re.sub(r'\bjr\.?\s*', 'jr ', d)
    d = re.sub(r'\bjiron\s+', 'jr ', d)
    d = re.sub(r'\bdpto\.?\s*', 'dpto ', d)
    d = re.sub(r'\bsec\.?\s*', 'sec ', d)
    d = re.sub(r'\betapa\s+', 'etapa ', d)
    d = re.sub(r'[.,;:#\-\(\)]', ' ', d)
    d = re.sub(r'\s+', ' ', d).strip()
    return d


def _direccion_similar(dir1, dir2, umbral=0.5):
    """Compara dos direcciones con Jaccard de tokens normalizados."""
    d1 = set(_normalizar_direccion(dir1).split())
    d2 = set(_normalizar_direccion(dir2).split())
    if not d1 or not d2:
        return False
    intersect = d1 & d2
    union = d1 | d2
    if not union:
        return False
    jaccard = len(intersect) / len(union)
    return jaccard >= umbral


def _nombre_completo_match(nombre_registrado, nombres_candidato):
    """Verifica que TODAS las palabras del nombre registrado aparezcan en el candidato."""
    if not nombre_registrado or not nombres_candidato:
        return False
    words_reg = [_unaccent(w).lower() for w in nombre_registrado.split() if w.strip()]
    words_cand = [_unaccent(w).lower() for w in nombres_candidato.split() if w.strip()]
    return all(w in words_cand for w in words_reg)


def _nombre_parcial_conflicto(nombre_registrado, nombres_candidato):
    """Detecta si el candidato tiene un segundo nombre que CONFLICTA con el registrado.
    Ej: registrado='CARLOS EDUARDO', candidato='CARLOS ENRIQUE' → conflicto.
    """
    words_reg = [_unaccent(w).lower() for w in nombre_registrado.split() if w.strip()]
    words_cand = [_unaccent(w).lower() for w in (nombres_candidato or "").split() if w.strip()]
    if len(words_reg) < 2 or len(words_cand) < 2:
        return False
    # Si el primer nombre coincide pero el segundo NO está en los nombres del candidato → conflicto
    if words_reg[0] == words_cand[0] and words_reg[1] not in words_cand:
        return True
    return False


def _buscar_pareja_en_bd(conn, nombres_pareja, ap_pat_pareja, titular_fila, es_padre_titular):
    """Busca en la base de datos a la pareja (madre o padre) para validar la relación familiar.

    Se filtra por sexo opuesto del titular y por ubigeo de DOMICILIO compartido
    (las parejas suelen convivir en el mismo distrito, aunque nazcan lejos).
    """
    nombres_tok, apellidos_tok = _separar_nombres_apellidos(_tokens_campo(nombres_pareja), ap_pat_pareja)
    primer_nombre = nombres_tok[0] if nombres_tok else ""
    nombres_completos = " ".join(nombres_tok)
    if apellidos_tok:
        ap_pat_clean = apellidos_tok[0]
    else:
        ap_pat_clean = _sanitize_word(ap_pat_pareja or "").lower()
    if not primer_nombre or not ap_pat_clean:
        return None

    tsq = _build_tsq(ap_pat_clean, *nombres_tok)
    ubigeo_dir = titular_fila.get("ubigeo_dir") or ""
    fecha_nac_titular = titular_fila.get("fecha_nac")
    sexo_pareja = "2" if es_padre_titular else "1"

    query = """
        SELECT dni, ap_pat, ap_mat, nombres, fecha_nac, ubigeo_nac, ubigeo_dir, direccion
        FROM personas
        WHERE search_vector @@ to_tsquery('simple', :tsq)
          AND lower(ap_pat) = :ap_pat
          AND (lower(nombres) = :nombres OR lower(nombres) LIKE :primer_nom || ' %')
          AND (sexo IS NULL OR sexo::text = :sexo_pareja)
          AND (:ubigeo_dir = '' OR ubigeo_dir = :ubigeo_dir
               OR SPLIT_PART(ubigeo_dir, '-', 1) = SPLIT_PART(:ubigeo_dir, '-', 1))
        LIMIT 5;
    """
    try:
        filas = conn.execute(text(query), {
            "tsq": tsq,
            "ap_pat": ap_pat_clean,
            "nombres": nombres_completos,
            "primer_nom": primer_nombre,
            "ubigeo_dir": ubigeo_dir,
            "sexo_pareja": sexo_pareja,
        }).mappings().all()

        for f in filas:
            if _es_edad_pareja_coherente(f.get("fecha_nac"), fecha_nac_titular):
                return dict(f)
    except Exception:
        logger.warning("Error buscando pareja '%s' en BD", nombres_pareja, exc_info=True)
    return None


def _build_tsq(*words) -> str:
    """Construye un tsquery seguro uniendo palabras con &."""
    clean = [_sanitize_word(w) for w in words if w and _sanitize_word(w)]
    return " & ".join(clean) if clean else ""


def _rerank_progenitor(filas, nombre_registrado, hijo_fila, fecha_nac_hijo, max_dif_edad):
    """Re-rankea top-N candidatos de progenitor con cross-validación Python-side.

    Aplica bonificaciones y penalizaciones que la SQL no puede calcular eficientemente:
    - Match completo de nombre multi-palabra
    - Penalización por conflicto de segundo nombre
    - Similitud de dirección normalizada (token Jaccard)
    """
    mejor = None
    mejor_score = -999999

    for fila in filas:
        if not _es_edad_progenitor_valida(fila.get("fecha_nac"), fecha_nac_hijo, min_dif=13, max_dif=max_dif_edad):
            continue

        score = fila.get("score", 0) or 0
        nombres_candidato = fila.get("nombres") or ""

        # Bonus: nombre completo registrado coincide con candidato
        if _nombre_completo_match(nombre_registrado, nombres_candidato):
            score += 6000

        # Penalización fuerte: segundo nombre conflicta
        if _nombre_parcial_conflicto(nombre_registrado, nombres_candidato):
            score -= 10000

        # Bonus: dirección similar normalizada
        dir_hijo = hijo_fila.get("direccion") or ""
        dir_cand = fila.get("direccion") or ""
        if dir_hijo and dir_cand and _direccion_similar(dir_hijo, dir_cand):
            score += 8000

        # Bonus cruzado: ubigeo domicilio del padre ≈ ubigeo nacimiento del hijo
        ubigeo_dir_cand = fila.get("ubigeo_dir") or ""
        ubigeo_nac_hijo = hijo_fila.get("ubigeo_nac") or ""
        if ubigeo_dir_cand and ubigeo_nac_hijo:
            if ubigeo_dir_cand == ubigeo_nac_hijo:
                score += 3000
            elif ubigeo_dir_cand and len(ubigeo_dir_cand) >= 4 and ubigeo_nac_hijo[:4] == ubigeo_dir_cand[:4]:
                score += 1500

        if score > mejor_score:
            mejor_score = score
            mejor = fila

    return mejor


def _buscar_padre(conn, padre_nombre, hijo_fila):
    """Busca al padre usando nombre completo multi-palabra, top-N re-ranking y validación biológica.

    El campo `padre` se separa primero en nombres de pila y apellidos usando el
    apellido heredado del hijo como ancla (`_separar_nombres_apellidos`), de modo
    que las comparaciones contra `p.nombres` nunca mezclen apellidos.
    """
    from app.sql.queries import BUSCAR_PADRE_RANKED

    tokens = _tokens_campo(padre_nombre)
    if not tokens:
        return None

    hijo_ap_pat = (hijo_fila.get("ap_pat") or "").strip()
    if not hijo_ap_pat:
        return None
    nombres_tok, apellidos_tok = _separar_nombres_apellidos(tokens, hijo_ap_pat)
    primer_nombre = nombres_tok[0] if nombres_tok else ""
    segundo_nombre = nombres_tok[1] if len(nombres_tok) > 1 else ""
    nombre_completo = " ".join(nombres_tok)
    padre_ap_mat = apellidos_tok[1] if len(apellidos_tok) > 1 else ""

    # Incluir TODOS los tokens del campo en el tsquery para mayor selectividad GIN
    tsq = _build_tsq(*tokens, hijo_ap_pat)
    if not tsq:
        return None

    fecha_nac = hijo_fila.get("fecha_nac")
    params = {
        "tsq": tsq,
        "padre_nombre": primer_nombre,
        "padre_segundo": segundo_nombre,
        "padre_nombre_completo": nombre_completo,
        "padre_ap_mat": padre_ap_mat,
        "hijo_ap_pat": hijo_ap_pat.lower(),
        "hijo_ubigeo_nac": (hijo_fila.get("ubigeo_nac") or ""),
        "hijo_ubigeo_dir": (hijo_fila.get("ubigeo_dir") or ""),
        "hijo_direccion": (hijo_fila.get("direccion") or "").strip().lower(),
        "hijo_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
    }

    try:
        filas = conn.execute(text(BUSCAR_PADRE_RANKED), params).mappings().all()
        if not filas and len(nombres_tok) > 1:
            # Fallback: si no hay resultados con todos los tokens, intentar solo primer nombre
            tsq_fallback = _build_tsq(primer_nombre, hijo_ap_pat)
            if tsq_fallback:
                params["tsq"] = tsq_fallback
                filas = conn.execute(text(BUSCAR_PADRE_RANKED), params).mappings().all()

        fila = _rerank_progenitor(filas, nombre_completo, hijo_fila, fecha_nac, max_dif_edad=75)
        if fila:
            nodo = _fila_a_nodo(fila)
            nodo["encontrado"] = True
            return nodo
        return None
    except Exception:
        logger.warning("Error buscando padre '%s'", padre_nombre, exc_info=True)
        return None


def _buscar_madre(conn, madre_nombre, hijo_fila):
    """Busca a la madre usando nombre completo multi-palabra, top-N re-ranking y validación biológica.

    Aplica la misma separación nombres/apellidos que `_buscar_padre`, anclada
    en el apellido materno del hijo (= apellido paterno de la madre).
    """
    from app.sql.queries import BUSCAR_MADRE_RANKED

    tokens = _tokens_campo(madre_nombre)
    if not tokens:
        return None

    hijo_ap_mat = (hijo_fila.get("ap_mat") or "").strip()
    if not hijo_ap_mat:
        return None
    nombres_tok, apellidos_tok = _separar_nombres_apellidos(tokens, hijo_ap_mat)
    primer_nombre = nombres_tok[0] if nombres_tok else ""
    segundo_nombre = nombres_tok[1] if len(nombres_tok) > 1 else ""
    nombre_completo = " ".join(nombres_tok)
    madre_ap_mat = apellidos_tok[1] if len(apellidos_tok) > 1 else ""

    # Incluir TODOS los tokens del campo en el tsquery para mayor selectividad GIN
    tsq = _build_tsq(*tokens, hijo_ap_mat)
    if not tsq:
        return None

    fecha_nac = hijo_fila.get("fecha_nac")
    params = {
        "tsq": tsq,
        "madre_nombre": primer_nombre,
        "madre_segundo": segundo_nombre,
        "madre_nombre_completo": nombre_completo,
        "madre_ap_mat": madre_ap_mat,
        "hijo_ap_mat": hijo_ap_mat.lower(),
        "hijo_ubigeo_nac": (hijo_fila.get("ubigeo_nac") or ""),
        "hijo_ubigeo_dir": (hijo_fila.get("ubigeo_dir") or ""),
        "hijo_direccion": (hijo_fila.get("direccion") or "").strip().lower(),
        "hijo_fecha_nac": str(fecha_nac) if fecha_nac else "1900-01-01",
    }

    try:
        filas = conn.execute(text(BUSCAR_MADRE_RANKED), params).mappings().all()
        if not filas and len(nombres_tok) > 1:
            # Fallback: si no hay resultados con todos los tokens, intentar solo primer nombre
            tsq_fallback = _build_tsq(primer_nombre, hijo_ap_mat)
            if tsq_fallback:
                params["tsq"] = tsq_fallback
                filas = conn.execute(text(BUSCAR_MADRE_RANKED), params).mappings().all()

        fila = _rerank_progenitor(filas, nombre_completo, hijo_fila, fecha_nac, max_dif_edad=55)
        if fila:
            nodo = _fila_a_nodo(fila)
            nodo["encontrado"] = True
            return nodo
        return None
    except Exception:
        logger.warning("Error buscando madre '%s'", madre_nombre, exc_info=True)
        return None


def _buscar_abuelo_safe(conn, nombre, progenitor_nodo, tipo, apellido_ref):
    """Busca un abuelo/abuela con timeout de seguridad (2s).

    Los abuelos frecuentemente tienen solo un nombre registrado (ej: 'MARIA').
    Nombres ultra-comunes como 'MARIA' (1.4M filas) producen escaneos GIN de
    15+ segundos sin resultados. Esta función usa un SAVEPOINT + statement_timeout
    para abortar la query si excede 2s sin romper la transacción principal.
    """
    sexo_hint = "Masculino" if tipo == "padre" else "Femenino"
    buscar_fn = _buscar_padre if tipo == "padre" else _buscar_madre

    try:
        conn.execute(text("SAVEPOINT abuelo_search"))
        conn.execute(text("SET LOCAL statement_timeout = '2000'"))
        resultado = buscar_fn(conn, nombre, progenitor_nodo)
        conn.execute(text("RELEASE SAVEPOINT abuelo_search"))

        if resultado and _es_edad_progenitor_valida(resultado.get("fecha_nac"), progenitor_nodo.get("fecha_nac")):
            return resultado
    except Exception:
        # Timeout u otro error — rollback al savepoint y continuar
        try:
            conn.execute(text("ROLLBACK TO SAVEPOINT abuelo_search"))
            conn.execute(text("RELEASE SAVEPOINT abuelo_search"))
        except Exception:
            pass
    finally:
        try:
            conn.execute(text("SET LOCAL statement_timeout = '0'"))
        except Exception:
            pass

    return _nodo_solo_nombre(nombre, sexo_hint, apellido_ref)


def construir_arbol(dni: str):
    """Construye el árbol genealógico con lógica biológica estricta y aceleración GIN.

    Factores de correlación y validación:
    - Regla biológica estricta: progenitores > descendientes (mínimo 13 años de diferencia)
    - Nombre de pila del padre/madre con desacentuación FTS
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
        conn.execute(text("SET work_mem = '64MB'"))

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
                # Abuelos paternos (con timeout para evitar scans lentos)
                abuelo_p_nombre = padre_nodo.get("padre")
                abuela_p_nombre = padre_nodo.get("madre")
                if abuelo_p_nombre and abuelo_p_nombre.strip():
                    resultado["abuelo_paterno"] = _buscar_abuelo_safe(
                        conn, abuelo_p_nombre, padre_nodo, "padre", padre_nodo.get("ap_pat")
                    )
                if abuela_p_nombre and abuela_p_nombre.strip():
                    resultado["abuela_paterna"] = _buscar_abuelo_safe(
                        conn, abuela_p_nombre, padre_nodo, "madre", padre_nodo.get("ap_mat")
                    )
            else:
                resultado["padre"] = _nodo_solo_nombre(padre_texto, "Masculino", persona_fila.get("ap_pat"))

        # 3. Buscar madre
        madre_texto = persona_fila.get("madre")
        if madre_texto and madre_texto.strip():
            madre_nodo = _buscar_madre(conn, madre_texto, persona_fila)
            if madre_nodo:
                resultado["madre"] = madre_nodo
                # Abuelos maternos (con timeout para evitar scans lentos)
                abuelo_m_nombre = madre_nodo.get("padre")
                abuela_m_nombre = madre_nodo.get("madre")
                if abuelo_m_nombre and abuelo_m_nombre.strip():
                    resultado["abuelo_materno"] = _buscar_abuelo_safe(
                        conn, abuelo_m_nombre, madre_nodo, "padre", madre_nodo.get("ap_pat")
                    )
                if abuela_m_nombre and abuela_m_nombre.strip():
                    resultado["abuela_materna"] = _buscar_abuelo_safe(
                        conn, abuela_m_nombre, madre_nodo, "madre", madre_nodo.get("ap_mat")
                    )
            else:
                resultado["madre"] = _nodo_solo_nombre(madre_texto, "Femenino", persona_fila.get("ap_mat"))

        # 4. Buscar hermanos (con re-ranking Python-side)
        ap_pat_hijo = (persona_fila.get("ap_pat") or "").strip()
        ap_mat_hijo = (persona_fila.get("ap_mat") or "").strip()

        tsq_hermanos = _build_tsq(ap_pat_hijo, ap_mat_hijo) or _build_tsq(ap_pat_hijo)
        if tsq_hermanos:
            hermanos_filas = conn.execute(
                text(BUSCAR_HERMANOS_RANKED),
                {
                    "tsq": tsq_hermanos,
                    "dni_excluir": dni,
                    "padre": (padre_texto or "").strip().lower(),
                    "madre": (madre_texto or "").strip().lower(),
                    "hijo_ap_pat": ap_pat_hijo.lower(),
                    "hijo_ap_mat": ap_mat_hijo.lower(),
                    "hijo_ubigeo_nac": (persona_fila.get("ubigeo_nac") or ""),
                    "hijo_ubigeo_dir": (persona_fila.get("ubigeo_dir") or ""),
                    "hijo_direccion": (persona_fila.get("direccion") or "").strip().lower(),
                    "hijo_fecha_nac": str(fecha_nac_persona) if fecha_nac_persona else "1900-01-01",
                },
            ).mappings().all()
            # Re-ranking Python-side: detectar conflictos de nombre de padres
            hermanos_reranked = _rerank_hermanos(hermanos_filas, persona_fila)
            resultado["hermanos"] = [_fila_a_nodo(h) for h in hermanos_reranked]

        # 5. Buscar hijos (con SAVEPOINT de seguridad y cross-validación)
        nombres_persona = (persona_fila.get("nombres") or "").strip().lower()
        ap_pat_persona = ap_pat_hijo
        ap_mat_persona = ap_mat_hijo
        sexo_persona = str(persona_fila.get("sexo") or "")
        es_padre = sexo_persona in ("1", "Masculino")

        primer_nombre_persona = _unaccent(nombres_persona.split()[0]) if nombres_persona.split() else ""
        tsq_hijos = _build_tsq(ap_pat_persona)

        d_persona = _parse_date(fecha_nac_persona)
        puede_tener_hijos = d_persona is not None and (date.today() - d_persona).days / 365.25 >= 16

        if tsq_hijos and primer_nombre_persona and puede_tener_hijos:
            min_fecha_hijo = str(d_persona + timedelta(days=int(13 * 365.25)))
            max_fecha_hijo = str(min(d_persona + timedelta(days=int(70 * 365.25)), date.today()))
            optimo_min_fecha = str(d_persona + timedelta(days=int(18 * 365.25)))
            optimo_max_fecha = str(min(d_persona + timedelta(days=int(42 * 365.25)), date.today()))

            # SAVEPOINT para proteger la transacción si la query excede el timeout
            hijos_filas = []
            try:
                conn.execute(text("SAVEPOINT hijos_search"))
                conn.execute(text("SET statement_timeout = '25000'"))
                hijos_filas = conn.execute(
                    text(BUSCAR_HIJOS_RANKED),
                    {
                        "tsq": tsq_hijos,
                        "progenitor_dni": dni,
                        "progenitor_nombre": primer_nombre_persona,
                        "progenitor_nombre_completo": _unaccent(nombres_persona),
                        "progenitor_ap_pat": ap_pat_persona.lower(),
                        "progenitor_ap_mat": ap_mat_persona.lower(),
                        "es_padre": es_padre,
                        "progenitor_ubigeo_nac": (persona_fila.get("ubigeo_nac") or ""),
                        "progenitor_ubigeo_dir": (persona_fila.get("ubigeo_dir") or ""),
                        "progenitor_direccion": (persona_fila.get("direccion") or "").strip().lower(),
                        "min_fecha_hijo": min_fecha_hijo,
                        "max_fecha_hijo": max_fecha_hijo,
                        "optimo_min_fecha": optimo_min_fecha,
                        "optimo_max_fecha": optimo_max_fecha,
                    },
                ).mappings().all()
                conn.execute(text("RELEASE SAVEPOINT hijos_search"))
            except Exception:
                logger.warning("Timeout o error buscando hijos para DNI %s", dni, exc_info=True)
                try:
                    conn.execute(text("ROLLBACK TO SAVEPOINT hijos_search"))
                    conn.execute(text("RELEASE SAVEPOINT hijos_search"))
                except Exception:
                    pass
            finally:
                try:
                    conn.execute(text("SET statement_timeout = '0'"))
                except Exception:
                    pass

            campo_progenitor = "padre" if es_padre else "madre"
            hijos_candidatos = [
                dict(h) for h in hijos_filas
                if _es_edad_hijo_valida(h.get("fecha_nac"), fecha_nac_persona)
                and _es_nombre_progenitor_compatible(
                    _unaccent(h.get(campo_progenitor) or ""),
                    _unaccent(nombres_persona),
                    _unaccent(ap_pat_persona),
                    _unaccent(ap_mat_persona)
                )
            ]

            if hijos_candidatos:
                # Re-ranking Python-side: desambiguación geográfica y por edad
                hijos_candidatos = _rerank_hijos(
                    hijos_candidatos, persona_fila, es_padre, conn
                )

                # Cross-validación con co-progenitor identificado
                otro_progenitor = resultado.get("madre") if es_padre else resultado.get("padre")
                if otro_progenitor and otro_progenitor.get("encontrado") and otro_progenitor.get("dni"):
                    otro_nombres = _unaccent((otro_progenitor.get("nombres") or "")).lower().split()
                    otro_ap_pat = _unaccent((otro_progenitor.get("ap_pat") or "")).lower()
                    campo_otro = "madre" if es_padre else "padre"

                    for h in hijos_candidatos:
                        texto_otro = _unaccent((h.get(campo_otro) or "")).lower()
                        tokens_otro = texto_otro.split()

                        if not tokens_otro:
                            continue

                        primer_nombre_otro = otro_nombres[0] if otro_nombres else ""
                        if primer_nombre_otro and primer_nombre_otro in tokens_otro:
                            # ¿Apellido del co-progenitor = ap_mat/ap_pat del hijo?
                            ap_hijo_cruzado = (h.get("ap_mat") if es_padre else h.get("ap_pat")) or ""
                            if otro_ap_pat and _unaccent(ap_hijo_cruzado).lower() == otro_ap_pat:
                                h["score"] = h.get("score", 0) + 20000  # CASI DEFINITIVO
                            else:
                                h["score"] = h.get("score", 0) + 8000
                        else:
                            # Co-progenitor NO coincide → probable hijo de OTRO homónimo
                            h["score"] = h.get("score", 0) - 15000

                    # Re-filtrar después de cross-validación
                    hijos_candidatos = [h for h in hijos_candidatos if h.get("score", 0) >= 25000]

                hijos_candidatos.sort(
                    key=lambda x: str(x.get("fecha_nac") or "1900-01-01")
                )
                resultado["hijos"] = [_fila_a_nodo(h) for h in hijos_candidatos]

        return resultado


def _rerank_hijos(hijos_candidatos, progenitor_fila, es_padre, conn):
    """Re-rankea y filtra hijos con desambiguación geográfica y cross-validación.

    Resuelve el problema de homónimos: cuando existen múltiples personas con el
    mismo nombre completo (ej: 9 'CESAR AUGUSTO NEVADO'), los hijos de TODOS
    se atribuían al titular. Esta función discrimina usando:

    1. Proximidad geográfica: ubigeo_nac del hijo vs ubigeo_nac/ubigeo_dir del progenitor
    2. Similitud de dirección normalizada
    3. Edad óptima reproductiva vs marginal
    4. Cross-validación con pareja encontrada en BD
    """
    prog_ubi_nac = (progenitor_fila.get("ubigeo_nac") or "").strip()
    prog_ubi_dir = (progenitor_fila.get("ubigeo_dir") or "").strip()
    prog_direccion = (progenitor_fila.get("direccion") or "").strip()
    prog_fecha_nac = progenitor_fila.get("fecha_nac")
    d_prog = _parse_date(prog_fecha_nac)

    campo_otro = "madre" if es_padre else "padre"
    pareja_cache: dict[str, bool] = {}

    for h in hijos_candidatos:
        score = h.get("score", 0) or 0
        h_ubi_nac = (h.get("ubigeo_nac") or "").strip()
        h_ubi_dir = (h.get("ubigeo_dir") or "").strip()
        h_direccion = (h.get("direccion") or "").strip()

        # --- 1. Proximidad geográfica ---
        geo_bonus = 0
        if h_ubi_nac and prog_ubi_nac:
            if h_ubi_nac == prog_ubi_nac:
                geo_bonus = max(geo_bonus, 6000)  # Distrito exacto de nacimiento
            elif len(h_ubi_nac) >= 4 and len(prog_ubi_nac) >= 4 and h_ubi_nac[:4] == prog_ubi_nac[:4]:
                geo_bonus = max(geo_bonus, 4000)  # Provincia de nacimiento
            elif len(h_ubi_nac) >= 2 and len(prog_ubi_nac) >= 2 and h_ubi_nac[:2] == prog_ubi_nac[:2]:
                geo_bonus = max(geo_bonus, 2000)  # Departamento de nacimiento

        if h_ubi_nac and prog_ubi_dir:
            # Cruce: hijo nació donde el padre vive
            prog_ubi_dir_clean = prog_ubi_dir.replace("-", " ").strip()
            # Comparar ubigeo código si existe
            if h_ubi_nac == prog_ubi_dir_clean:
                geo_bonus = max(geo_bonus, 5000)
            elif len(h_ubi_nac) >= 4 and len(prog_ubi_dir_clean) >= 4 and h_ubi_nac[:4] == prog_ubi_dir_clean[:4]:
                geo_bonus = max(geo_bonus, 3500)
            elif len(h_ubi_nac) >= 2 and len(prog_ubi_dir_clean) >= 2 and h_ubi_nac[:2] == prog_ubi_dir_clean[:2]:
                geo_bonus = max(geo_bonus, 1500)

        # Coincidencia de ubigeo de domicilio (residencia actual)
        if h_ubi_dir and prog_ubi_dir:
            if h_ubi_dir.strip().lower() == prog_ubi_dir.strip().lower():
                geo_bonus = max(geo_bonus, 8000)  # Mismo distrito de residencia actual
            else:
                p_parts = [x.strip().lower() for x in prog_ubi_dir.split("-") if x.strip()]
                h_parts = [x.strip().lower() for x in h_ubi_dir.split("-") if x.strip()]
                if len(p_parts) >= 2 and len(h_parts) >= 2 and p_parts[:2] == h_parts[:2]:
                    geo_bonus = max(geo_bonus, 4000)  # Misma provincia de residencia

        # Penalización geográfica: departamento totalmente diferente
        if h_ubi_nac and prog_ubi_nac and len(h_ubi_nac) >= 2 and len(prog_ubi_nac) >= 2:
            if h_ubi_nac[:2] != prog_ubi_nac[:2]:
                # Verificar también contra ubigeo_dir
                dir_match = False
                if prog_ubi_dir:
                    prog_dir_clean = prog_ubi_dir.replace("-", " ").strip()
                    if len(prog_dir_clean) >= 2 and h_ubi_nac[:2] == prog_dir_clean[:2]:
                        dir_match = True
                if not dir_match:
                    geo_bonus -= 8000  # Departamento completamente diferente (penalización fuerte)

        score += geo_bonus

        # --- 2. Similitud de dirección ---
        if prog_direccion and h_direccion and _direccion_similar(prog_direccion, h_direccion):
            score += 25000  # Mismo domicilio físico (evidencia casi concluyente de convivencia)
            h["mismo_domicilio"] = True

        # --- 3. Edad reproductiva refinada ---
        if d_prog:
            d_hijo = _parse_date(h.get("fecha_nac"))
            if d_hijo:
                edad_al_nacer = (d_hijo - d_prog).days / 365.25
                if edad_al_nacer < 15:
                    score -= 8000  # Padre tenía < 15 años: muy improbable
                elif edad_al_nacer < 18:
                    score -= 3000  # Padre tenía 15-17: poco probable
                elif 20 <= edad_al_nacer <= 45:
                    score += 2000  # Rango óptimo

        # --- 4. Cross-validación con pareja ---
        otro_texto = (h.get(campo_otro) or "").strip()
        clave = " ".join(_unaccent(otro_texto).lower().split())
        if clave:
            if clave not in pareja_cache:
                if len(pareja_cache) >= 8:
                    pareja_cache[clave] = False
                else:
                    apellido_ref = (h.get("ap_mat") if es_padre else h.get("ap_pat")) or ""
                    pareja = _buscar_pareja_en_bd(conn, otro_texto, apellido_ref, progenitor_fila, es_padre)
                    pareja_cache[clave] = bool(
                        pareja
                        and _es_nombre_progenitor_compatible(
                            clave,
                            _unaccent(pareja.get("nombres") or ""),
                            _unaccent(pareja.get("ap_pat") or ""),
                            _unaccent(pareja.get("ap_mat") or ""),
                        )
                    )
            if pareja_cache.get(clave, False):
                score += 10000

        h["score"] = score

    # --- 5. Descarte de homónimos cuando hay hijos confirmados en casa ---
    hijos_en_casa = [h for h in hijos_candidatos if h.get("mismo_domicilio")]
    if hijos_en_casa:
        coparents_en_casa = set()
        for h in hijos_en_casa:
            otro = _unaccent(h.get(campo_otro) or "").lower().strip()
            tokens = otro.split()
            if tokens:
                coparents_en_casa.add(tokens[0])

        for h in hijos_candidatos:
            if not h.get("mismo_domicilio"):
                otro = _unaccent(h.get(campo_otro) or "").lower().strip()
                tokens = otro.split()
                # Si el co-progenitor es diferente al de los hijos en casa, penalizar fuertemente
                if not tokens or tokens[0] not in coparents_en_casa:
                    h["score"] = h.get("score", 0) - 25000

    # --- Bonus por consistencia de co-progenitor (clustering) ---
    campo_otro = "madre" if es_padre else "padre"
    coparent_counts: dict[str, int] = {}
    for h in hijos_candidatos:
        otro_texto = _unaccent((h.get(campo_otro) or "")).lower().strip()
        tokens_otro = otro_texto.split()
        key = tokens_otro[0] if tokens_otro else "_sin_"
        coparent_counts[key] = coparent_counts.get(key, 0) + 1

    for h in hijos_candidatos:
        otro_texto = _unaccent((h.get(campo_otro) or "")).lower().strip()
        tokens_otro = otro_texto.split()
        key = tokens_otro[0] if tokens_otro else "_sin_"
        count = coparent_counts.get(key, 0)
        if count >= 3:
            h["score"] = h.get("score", 0) + 8000   # 3+ hijos con misma madre → alta confianza
        elif count == 2:
            h["score"] = h.get("score", 0) + 4000   # 2 hijos con misma madre → confianza media
        # 1 hijo aislado → sin bonus (posible falso positivo)

    # --- Filtrado con gap analysis ---
    if not hijos_candidatos:
        return []

    scores = sorted([h.get("score", 0) for h in hijos_candidatos], reverse=True)
    max_score = scores[0]

    # 1. Detectar "gap natural": caída de >15000 puntos entre grupos
    umbral_gap = None
    for i in range(1, len(scores)):
        gap = scores[i - 1] - scores[i]
        if gap >= 15000 and scores[i - 1] >= 40000:
            umbral_gap = scores[i - 1]  # Solo mantener grupo superior
            break

    if umbral_gap is not None:
        return [h for h in hijos_candidatos if h.get("score", 0) >= umbral_gap]

    # 2. Sin gap claro: umbral relativo estricto
    if max_score >= 60000:
        umbral_efectivo = max_score - 8000
    elif max_score >= 45000:
        umbral_efectivo = max_score - 6000
    else:
        umbral_efectivo = max(25000, max_score - 5000)

    hijos_filtrados = [
        h for h in hijos_candidatos
        if h.get("score", 0) >= umbral_efectivo
    ]

    return hijos_filtrados


def _rerank_hermanos(hermanos_filas, persona_fila):
    """Re-rankea hermanos con validación estricta de nombres de padres.

    Detecta y elimina falsos hermanos que comparten apellidos pero cuyos
    padres tienen segundos nombres diferentes (ej: padre del titular es
    'JUAN CARLOS' pero el candidato tiene padre 'JUAN PEDRO').

    También aplica bonificaciones por dirección compartida y ubigeo
    de nacimiento idéntico para priorizar hermanos reales.
    """
    padre_titular = _unaccent((persona_fila.get("padre") or "")).lower().strip()
    madre_titular = _unaccent((persona_fila.get("madre") or "")).lower().strip()
    dir_titular = (persona_fila.get("direccion") or "").strip()
    ubi_nac_titular = (persona_fila.get("ubigeo_nac") or "").strip()

    filtrados = []
    for h in hermanos_filas:
        h = dict(h)
        score = h.get("score", 0) or 0
        padre_h = _unaccent((h.get("padre") or "")).lower().strip()
        madre_h = _unaccent((h.get("madre") or "")).lower().strip()

        # --- Conflicto de segundo nombre del padre ---
        if padre_titular and padre_h:
            if _nombre_parcial_conflicto(padre_titular, padre_h):
                continue  # Descartar: padre="JUAN CARLOS" vs "JUAN PEDRO"
            if _nombre_completo_match(padre_titular, padre_h):
                score += 3000  # Nombre completo de padre coincide exactamente

        # --- Conflicto de segundo nombre de la madre ---
        if madre_titular and madre_h:
            if _nombre_parcial_conflicto(madre_titular, madre_h):
                continue  # Descartar: madre="MARIA ELENA" vs "MARIA ROSA"
            if _nombre_completo_match(madre_titular, madre_h):
                score += 3000

        # --- Bonus por dirección compartida ---
        dir_h = (h.get("direccion") or "").strip()
        if dir_titular and dir_h and _direccion_similar(dir_titular, dir_h):
            score += 5000

        # --- Bonus por ubigeo nacimiento idéntico ---
        ubi_h = (h.get("ubigeo_nac") or "").strip()
        if ubi_nac_titular and ubi_h and ubi_nac_titular == ubi_h:
            score += 3000

        h["score"] = score
        filtrados.append(h)

    return filtrados

