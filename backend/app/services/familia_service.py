"""Motor de búsqueda familiar con confianza y evidencia.

El objetivo de este módulo es doble:

1. **Precisión**: cada relación se puntúa con evidencia verificable (apellido
   heredado, nombre, sexo, edad, ubigeo y domicilio) y se descartan las
   combinaciones biológicamente imposibles.
2. **Cobertura**: no se queda con el primer resultado. Se analizan todos los
   candidatos posibles dentro de un límite configurable, se devuelven las
   alternativas y se indica el nivel de confianza.

Los campos ``padre`` y ``madre`` del padrón suelen contener solo nombres de
pila (1-2 palabras). Por eso el apellido heredado del hijo se usa como ancla
para localizar al progenitor y para separar nombres de apellidos cuando el
campo sí los incluye.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app import config
from app.db import engine
from app.errors import QueryExecutionError

logger = logging.getLogger(__name__)

# ── Ubigeo ──────────────────────────────────────────────────────────────
# Códigos de departamento del ubigeo peruano (los dos primeros dígitos).
DEPARTAMENTOS: dict[str, str] = {
    "01": "AMAZONAS",
    "02": "ANCASH",
    "03": "APURIMAC",
    "04": "AREQUIPA",
    "05": "AYACUCHO",
    "06": "CAJAMARCA",
    "07": "CALLAO",
    "08": "CUSCO",
    "09": "HUANCAVELICA",
    "10": "HUANUCO",
    "11": "ICA",
    "12": "JUNIN",
    "13": "LA LIBERTAD",
    "14": "LAMBAYEQUE",
    "15": "LIMA",
    "16": "LORETO",
    "17": "MADRE DE DIOS",
    "18": "MOQUEGUA",
    "19": "PASCO",
    "20": "PIURA",
    "21": "PUNO",
    "22": "SAN MARTIN",
    "23": "TACNA",
    "24": "TUMBES",
    "25": "UCAYALI",
}

_ALIAS_DEPARTAMENTO: dict[str, str] = {
    "AMAZONAS": "01",
    "ANCASH": "02",
    "APURIMAC": "03",
    "AREQUIPA": "04",
    "AYACUCHO": "05",
    "CAJAMARCA": "06",
    "CALLAO": "07",
    "PROVINCIA CONSTITUCIONAL DEL CALLAO": "07",
    "CUSCO": "08",
    "HUANCAVELICA": "09",
    "HUANUCO": "10",
    "ICA": "11",
    "JUNIN": "12",
    "LA LIBERTAD": "13",
    "LAMBAYEQUE": "14",
    "LIMA": "15",
    "LIMA METROPOLITANA": "15",
    "LORETO": "16",
    "MADRE DE DIOS": "17",
    "MOQUEGUA": "18",
    "PASCO": "19",
    "PIURA": "20",
    "PUNO": "21",
    "SAN MARTIN": "22",
    "TACNA": "23",
    "TUMBES": "24",
    "UCAYALI": "25",
}

_CAMPOS_CANDIDATO = """
    p.dni, p.ap_pat, p.ap_mat, p.nombres, p.padre, p.madre,
    p.fecha_nac, p.ubigeo_nac, p.ubigeo_dir, p.direccion,
    p.est_civil, p.dig_ruc, p.fch_inscripcion, p.fch_emision, p.fch_caducidad,
    CASE
        WHEN p.sexo::text = '1' THEN 'Masculino'
        WHEN p.sexo::text = '2' THEN 'Femenino'
        ELSE NULLIF(btrim(p.sexo::text), '')
    END AS sexo,
    EXTRACT(YEAR FROM age(current_date, p.fecha_nac))::int AS edad_anios
"""


# ── Normalización ───────────────────────────────────────────────────────


def normalizar(valor: Any) -> str:
    """Minúsculas, sin acentos, sin signos y con espacios colapsados."""
    if valor is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(valor))
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def tokenizar(valor: Any) -> list[str]:
    """Devuelve los tokens normalizados y no vacíos de un texto."""
    return [t for t in normalizar(valor).split() if t]


def _fecha(valor: Any) -> date | None:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _anios_entre(nacimiento: Any, referencia: Any) -> float | None:
    """Años cumplidos entre dos fechas (referencia - nacimiento)."""
    d_nac = _fecha(nacimiento)
    d_ref = _fecha(referencia)
    if not d_nac or not d_ref:
        return None
    return (d_ref - d_nac).days / 365.25


_EVIDENCIA_NOMBRE_FUERTE = {"nombre_exacto", "nombre_ordenado", "nombre_tokens"}


def _nombre_es_fuerte(ev_nombre: list[dict]) -> bool:
    return any(e.get("codigo") in _EVIDENCIA_NOMBRE_FUERTE for e in ev_nombre)


def _nivel_confianza(puntos: float) -> str:
    if puntos >= config.FAMILIA_UMBRAL_ALTA:
        return "alta"
    if puntos >= config.FAMILIA_UMBRAL_MEDIA:
        return "media"
    return "baja"


def _evidencia(codigo: str, descripcion: str, puntos: int) -> dict[str, Any]:
    return {"codigo": codigo, "descripcion": descripcion, "puntos": puntos}


# ── Ubigeo ──────────────────────────────────────────────────────────────


def departamento_de_ubigeo_nac(codigo: Any) -> str:
    """Código de departamento a partir de un ubigeo de nacimiento."""
    limpio = re.sub(r"\D", "", str(codigo or ""))
    return limpio[:2] if len(limpio) >= 2 else ""


def departamento_de_ubigeo_dir(valor: Any) -> str:
    """Código de departamento a partir del texto ``DEP-PROV-DIST``.

    El padrón usa dos formatos: ``LIMA-LIMA-SAN MARTIN DE PORRES`` y
    `` -CALLAO-CALLAO`` (con el departamento vacío). También se acepta un
    ubigeo numérico de seis dígitos.
    """
    if valor is None:
        return ""
    texto = str(valor).strip()
    if not texto:
        return ""
    solo_digitos = re.sub(r"\D", "", texto)
    if len(solo_digitos) == 6 and not re.search(r"[A-Za-z]", texto):
        return solo_digitos[:2]

    partes = [normalizar(p) for p in texto.split("-") if normalizar(p)]
    for parte in partes:
        if parte in _ALIAS_DEPARTAMENTO:
            return _ALIAS_DEPARTAMENTO[parte]
    # Algunos registros usan "PROVINCIA CONSTITUCIONAL DEL CALLAO" con guiones.
    unido = normalizar(texto)
    for nombre, codigo in _ALIAS_DEPARTAMENTO.items():
        if nombre in unido:
            return codigo
    return ""


def _misma_provincia(ubigeo_a: Any, ubigeo_b: Any) -> bool:
    a = re.sub(r"\D", "", str(ubigeo_a or ""))
    b = re.sub(r"\D", "", str(ubigeo_b or ""))
    return len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4]


def _mismo_distrito(ubigeo_a: Any, ubigeo_b: Any) -> bool:
    a = re.sub(r"\D", "", str(ubigeo_a or ""))
    b = re.sub(r"\D", "", str(ubigeo_b or ""))
    return len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6]


def _evidencia_geografica(candidato: dict, referencia: dict) -> tuple[int, list[dict]]:
    """Compara nacimiento y domicilio sin cruzar códigos con nombres."""
    puntos = 0
    evidencias: list[dict] = []

    nac_c = candidato.get("ubigeo_nac")
    nac_r = referencia.get("ubigeo_nac")
    dir_c = candidato.get("ubigeo_dir")
    dir_r = referencia.get("ubigeo_dir")

    if _mismo_distrito(nac_c, nac_r):
        puntos += 6
        evidencias.append(_evidencia("ubigeo_nac_distrito", "Mismo distrito de nacimiento", 6))
    elif _misma_provincia(nac_c, nac_r):
        puntos += 4
        evidencias.append(_evidencia("ubigeo_nac_provincia", "Misma provincia de nacimiento", 4))
    elif departamento_de_ubigeo_nac(nac_c) and (departamento_de_ubigeo_nac(nac_c) == departamento_de_ubigeo_nac(nac_r)):
        puntos += 2
        evidencias.append(_evidencia("ubigeo_nac_departamento", "Mismo departamento de nacimiento", 2))

    dep_dir_c = departamento_de_ubigeo_dir(dir_c)
    dep_dir_r = departamento_de_ubigeo_dir(dir_r)
    dir_c_norm, dir_r_norm = normalizar(dir_c), normalizar(dir_r)
    if dir_c_norm and dir_c_norm == dir_r_norm:
        puntos += 5
        evidencias.append(_evidencia("ubigeo_dir_igual", "Mismo ubigeo de residencia", 5))
    else:
        if dep_dir_c and dep_dir_c == dep_dir_r:
            puntos += 4
            evidencias.append(_evidencia("ubigeo_dir_departamento", "Mismo departamento de residencia", 4))

    # Cruce válido: código de nacimiento contra departamento del domicilio.
    dep_nac_c = departamento_de_ubigeo_nac(nac_c)
    dep_nac_r = departamento_de_ubigeo_nac(nac_r)
    if dep_dir_r and dep_nac_c and dep_dir_r == dep_nac_c:
        puntos += 2
        evidencias.append(_evidencia("nac_candidato_dir_referencia", "Nació donde reside la referencia", 2))
    if dep_dir_c and dep_nac_r and dep_dir_c == dep_nac_r:
        puntos += 2
        evidencias.append(_evidencia("dir_candidato_nac_referencia", "Reside donde nació la referencia", 2))

    return min(puntos, 12), evidencias


def _evidencia_documental(candidato: dict, referencia: dict) -> tuple[int, list[dict]]:
    """Usa fechas de inscripción/emisión/caducidad como apoyo, nunca como prueba única."""
    puntos = 0
    evidencias: list[dict] = []
    for campo, codigo, descripcion, valor in (
        ("fch_inscripcion", "misma_inscripcion", "Misma fecha de inscripción", 4),
        ("fch_emision", "misma_emision", "Misma fecha de emisión", 3),
        ("fch_caducidad", "misma_caducidad", "Misma fecha de caducidad", 2),
    ):
        a = _fecha(candidato.get(campo))
        b = _fecha(referencia.get(campo))
        if a and b and a == b:
            puntos += valor
            evidencias.append(_evidencia(codigo, descripcion, valor))
    return min(puntos, 6), evidencias


def _normalizar_direccion(valor: Any) -> str:
    texto = normalizar(valor)
    reemplazos = {
        r"\bmz\b": "mz",
        r"\bmza\b": "mz",
        r"\bmanzana\b": "mz",
        r"\blt\b": "lt",
        r"\blote\b": "lt",
        r"\bav\b": "av",
        r"\bavenida\b": "av",
        r"\bjr\b": "jr",
        r"\bjiron\b": "jr",
        r"\bdpto\b": "dpto",
        r"\bsec\b": "sec",
        r"\betapa\b": "etapa",
    }
    for patron, reemplazo in reemplazos.items():
        texto = re.sub(patron, reemplazo, texto)
    return re.sub(r"\s+", " ", texto).strip()


def _evidencia_direccion(candidato: dict, referencia: dict) -> tuple[int, list[dict]]:
    dir_c = _normalizar_direccion(candidato.get("direccion"))
    dir_r = _normalizar_direccion(referencia.get("direccion"))
    if not dir_c or not dir_r:
        return 0, []
    if dir_c == dir_r:
        return 12, [_evidencia("misma_direccion", "Mismo domicilio registrado", 12)]

    def numero(texto: str) -> str:
        for token in reversed(texto.split()):
            if re.search(r"\d", token):
                return re.sub(r"\D", "", token)
        return ""

    num_c, num_r = numero(dir_c), numero(dir_r)
    tokens_c = set(dir_c.split())
    tokens_r = set(dir_r.split())
    jaccard = len(tokens_c & tokens_r) / len(tokens_c | tokens_r) if tokens_c and tokens_r else 0

    if num_c and num_r and num_c != num_r and jaccard >= 0.34:
        return -5, [_evidencia("numero_direccion_distinto", "El número de domicilio no coincide", -5)]
    if num_c and num_c == num_r and jaccard >= 0.34:
        return 10, [_evidencia("mismo_numero_direccion", "Mismo número de domicilio y vía similar", 10)]
    if jaccard >= 0.6:
        return 4, [_evidencia("direccion_similar", "Domicilio similar", 4)]
    return 0, []


# ── Separación de nombres y apellidos ───────────────────────────────────


def separar_nombres_apellidos(texto: Any, apellido_ancla: Any) -> tuple[list[str], list[str]]:
    """Separa un campo ``padre``/``madre`` usando el apellido heredado.

    Formatos contemplados:
    - ``JUAN GARCIA``      → nombres [JUAN], apellidos [GARCIA]
    - ``GARCIA JUAN``      → nombres [JUAN], apellidos [GARCIA]
    - ``GARCIA PEREZ JUAN``→ nombres [JUAN], apellidos [GARCIA, PEREZ]
    - ``JUAN``             → nombres [JUAN], apellidos []
    - ``MARIA``            → nombres [MARIA], apellidos []

    Si el ancla no aparece, se asume que todo el campo son nombres de pila.
    Esto evita el error histórico de tratar un segundo nombre como apellido.
    """
    tokens = tokenizar(texto)
    if not tokens:
        return [], []

    ancla = normalizar(apellido_ancla)
    if ancla and ancla in tokens:
        indice = tokens.index(ancla)
        if indice == 0:
            # Formato "APELLIDOS NOMBRES": como máximo dos apellidos.
            cantidad_apellidos = 2 if len(tokens) >= 3 else 1
            return tokens[cantidad_apellidos:], tokens[:cantidad_apellidos]
        return tokens[:indice], tokens[indice:]

    return tokens, []


def _compatibilidad_campos_progenitor(a: Any, b: Any) -> tuple[int, bool, list[dict]]:
    """Compara dos campos de progenitor (texto contra texto).

    Devuelve (puntos, conflicto, evidencias). Un conflicto significa que los
    textos no pueden corresponder a la misma persona (por ejemplo, segundo
    nombre distinto).
    """
    ta = tokenizar(a)
    tb = tokenizar(b)
    if not ta or not tb:
        return 0, False, []
    if ta == tb:
        return 30, False, [_evidencia("progenitor_exacto", "Nombre del progenitor coincide", 30)]

    corto, largo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if largo[: len(corto)] == corto:
        # Un solo nombre de pila ("MANUEL") frente a un nombre compuesto
        # ("MANUEL JESUS") es evidencia débil: muchas personas comparten el
        # primer nombre. No basta por sí solo para afirmar una relación.
        if len(corto) == 1 and len(largo) >= 2:
            return (
                10,
                False,
                [
                    _evidencia(
                        "progenitor_primer_nombre",
                        "Solo coincide el primer nombre del progenitor",
                        10,
                    )
                ],
            )
        return 20, False, [_evidencia("progenitor_prefijo", "Nombre del progenitor coincide parcialmente", 20)]
    if set(corto).issubset(set(largo)):
        if len(corto) == 1:
            return (
                8,
                False,
                [
                    _evidencia(
                        "progenitor_token_unico",
                        "Coincide un único token del nombre del progenitor",
                        8,
                    )
                ],
            )
        return 15, False, [_evidencia("progenitor_tokens", "Tokens del progenitor contenidos", 15)]
    if ta[0] == tb[0] and len(ta) >= 2 and len(tb) >= 2 and ta[1] != tb[1]:
        return 0, True, [_evidencia("progenitor_conflicto", "Segundo nombre del progenitor no coincide", -25)]
    if not (set(ta) & set(tb)):
        return 0, True, [_evidencia("progenitor_distinto", "Nombre del progenitor incompatible", -25)]
    coincidencias = len(set(ta) & set(tb)) / max(len(set(ta)), len(set(tb)))
    if coincidencias >= 0.5:
        return 8, False, [_evidencia("progenitor_parcial", "Coincidencia parcial del progenitor", 8)]
    return 0, True, [_evidencia("progenitor_conflicto", "Nombre del progenitor incompatible", -25)]


def _puntuar_nombre_registrado(
    registrado: Any,
    candidato_nombres: Any,
    candidato_ap_pat: Any,
    candidato_ap_mat: Any,
    apellido_ancla: Any = "",
    *,
    estricto: bool = False,
) -> tuple[int, bool, list[dict]]:
    """Puntúa el nombre de un candidato contra el campo registrado.

    El campo registrado puede traer solo el primer nombre, varios nombres o
    nombres y apellidos. Se compara contra ``nombres`` del candidato y se
    tolera que el candidato tenga nombres adicionales (el padrón suele estar
    más completo que el campo de filiación).

    Con ``estricto=True`` se penaliza que el campo registrado solo aporte
    parte del nombre. Se usa al buscar hijos: un campo ``madre = 'MILAGROS'``
    no confirma por sí solo a una madre llamada ``MILAGROS MARIA``.
    """
    nombres_reg, apellidos_reg = separar_nombres_apellidos(registrado, apellido_ancla)
    if not nombres_reg:
        return 0, False, []

    nombres_cand = tokenizar(candidato_nombres)
    ap_pat_cand = normalizar(candidato_ap_pat)
    ap_mat_cand = normalizar(candidato_ap_mat)
    universo_cand = set(nombres_cand) | {ap_pat_cand, ap_mat_cand} | set(apellidos_reg)

    coincidentes = [t for t in nombres_reg if t in nombres_cand]
    cobertura = len(coincidentes) / len(nombres_reg)

    puntos = 0
    evidencias: list[dict] = []
    if cobertura == 1:
        if nombres_cand == nombres_reg:
            puntos = 30
            evidencias.append(_evidencia("nombre_exacto", "Nombre completo coincide", 30))
        elif len(nombres_reg) >= 2 and nombres_cand[: len(nombres_reg)] == nombres_reg:
            puntos = 28 if not estricto else 15
            evidencias.append(
                _evidencia(
                    "nombre_ordenado",
                    "Nombres coinciden en orden",
                    puntos,
                )
            )
        elif len(nombres_reg) == 1 and len(nombres_cand) > 1:
            # "MANUEL" contra "MANUEL JESUS" no confirma por sí solo:
            # comparte el primer nombre con muchísimas personas.
            puntos = 15 if not estricto else 10
            evidencias.append(
                _evidencia(
                    "nombre_primer_token",
                    "Solo coincide el primer nombre registrado",
                    puntos,
                )
            )
        else:
            puntos = 25 if not estricto else 15
            evidencias.append(
                _evidencia(
                    "nombre_tokens",
                    "Todos los nombres registrados coinciden",
                    puntos,
                )
            )
    elif cobertura >= 0.5:
        puntos = 12 if not estricto else 8
        evidencias.append(_evidencia("nombre_parcial", "Coincidencia parcial de nombres", puntos))
    else:
        puntos = -20 if not estricto else -25
        evidencias.append(_evidencia("nombre_distinto", "Nombres no coinciden", puntos))

    conflicto = False
    if len(nombres_reg) >= 2 and nombres_reg[0] in nombres_cand and nombres_reg[1] not in nombres_cand:
        segundo = nombres_reg[1]
        if segundo not in {ap_pat_cand, ap_mat_cand} and segundo not in apellidos_reg:
            puntos -= 25
            conflicto = True
            evidencias.append(_evidencia("segundo_nombre_conflicto", "Segundo nombre no coincide", -25))

    faltantes = [t for t in nombres_reg if t not in universo_cand]
    if faltantes:
        penalidad = 10 if estricto else 8
        puntos -= penalidad * len(faltantes)
        evidencias.append(
            _evidencia(
                "nombre_faltante",
                "Parte del nombre no aparece en el candidato",
                -penalidad * len(faltantes),
            )
        )

    return max(-50, min(30, puntos)), conflicto, evidencias


# ── Acceso a datos ──────────────────────────────────────────────────────


def _query(
    conn,
    sql: str,
    params: dict[str, Any],
    *,
    timeout_ms: int = 7000,
    strict: bool = True,
) -> list[dict]:
    """Ejecuta una consulta con savepoint y timeout, sin romper la sesión.

    Las consultas de candidatos son tolerantes: si una variante expira se
    descarta y el árbol se construye con el resto. La consulta de la
    persona titular sí es estricta.
    """
    try:
        conn.execute(text("SAVEPOINT familia_query"))
        conn.execute(text(f"SET LOCAL statement_timeout = '{int(timeout_ms)}'"))
        filas = conn.execute(text(sql), params).mappings().all()
        conn.execute(text("RELEASE SAVEPOINT familia_query"))
        return [dict(f) for f in filas]
    except Exception as exc:
        logger.warning("Consulta familiar cancelada o fallida: %s", type(exc).__name__)
        try:
            conn.execute(text("ROLLBACK TO SAVEPOINT familia_query"))
            conn.execute(text("RELEASE SAVEPOINT familia_query"))
        except Exception:
            logger.debug("No se pudo liberar el savepoint familiar", exc_info=True)
        if strict:
            raise QueryExecutionError("No se pudo ejecutar la consulta familiar") from exc
        return []


def _rango_fechas_progenitor(hijo: dict, tipo: str) -> tuple[str, str]:
    """Rango de nacimiento posible para un progenitor."""
    fecha_hijo = _fecha(hijo.get("fecha_nac"))
    if not fecha_hijo:
        return "", ""
    max_dif = 85 if tipo == "padre" else 80
    min_dif = 13
    fecha_max = fecha_hijo - timedelta(days=int(min_dif * 365.25))
    fecha_min = fecha_hijo - timedelta(days=int(max_dif * 365.25))
    return fecha_min.isoformat(), fecha_max.isoformat()


def _buscar_candidatos_progenitor(conn, hijo: dict, tipo: str) -> list[dict]:
    """Genera candidatos a padre/madre con el apellido heredado como ancla."""
    campo = "padre" if tipo == "padre" else "madre"
    texto = hijo.get(campo)
    if not texto or not str(texto).strip():
        return []

    ancla = normalizar(hijo.get("ap_pat") if tipo == "padre" else hijo.get("ap_mat"))
    nombres, apellidos = separar_nombres_apellidos(texto, ancla)
    ap_mat_extra = apellidos[1] if len(apellidos) > 1 else ""

    tokens_base = list(dict.fromkeys(nombres + apellidos))
    if ancla and ancla not in tokens_base:
        tokens_base.append(ancla)

    variantes: list[str] = []
    if tokens_base:
        variantes.append(" & ".join(tokens_base))
    if nombres and ancla:
        variante = " & ".join([nombres[0], ancla])
        if variante not in variantes:
            variantes.append(variante)
    if ancla and not nombres and ancla not in variantes:
        variantes.append(ancla)
    if not variantes:
        return []

    sexo = "1" if tipo == "padre" else "2"
    fecha_min, fecha_max = _rango_fechas_progenitor(hijo, tipo)
    limite = config.FAMILIA_CANDIDATOS
    candidatos: dict[str, dict] = {}

    for indice, tsq in enumerate(variantes):
        condiciones = [
            "p.search_vector @@ to_tsquery('simple', :tsq)",
            "(:ancla = '' OR immutable_unaccent(lower(p.ap_pat)) = :ancla)",
            "(:ap_mat_extra = '' OR immutable_unaccent(lower(p.ap_mat)) = :ap_mat_extra)",
            "(:sexo = '' OR p.sexo::text = :sexo OR p.sexo IS NULL OR btrim(p.sexo::text) = '')",
            "(:fecha_min = '' OR p.fecha_nac IS NULL OR p.fecha_nac >= CAST(:fecha_min AS date))",
            "(:fecha_max = '' OR p.fecha_nac IS NULL OR p.fecha_nac <= CAST(:fecha_max AS date))",
        ]
        sql = f"""
            SELECT {_CAMPOS_CANDIDATO}
            FROM personas p
            WHERE {" AND ".join(condiciones)}
            ORDER BY ts_rank_cd(p.search_vector, to_tsquery('simple', :tsq)) DESC,
                     p.fecha_nac DESC NULLS LAST
            LIMIT :limite
        """
        filas = _query(
            conn,
            sql,
            {
                "tsq": tsq,
                "ancla": ancla,
                # En la variante reducida no se exige el segundo apellido:
                # puede ser un nombre mal separado o un apellido omitido.
                "ap_mat_extra": ap_mat_extra if indice == 0 else "",
                "sexo": sexo,
                "fecha_min": fecha_min,
                "fecha_max": fecha_max,
                "limite": limite,
            },
            timeout_ms=5000 if indice == 0 else 3500,
            strict=False,
        )
        for fila in filas:
            dni = str(fila.get("dni") or "")
            if dni and dni not in candidatos:
                candidatos[dni] = fila

        # Si la primera variante ya produce evidencia suficiente, no hace
        # falta seguir; si no, se prueba la variante reducida.
        if candidatos and indice == 0:
            mejor = 0
            for fila in candidatos.values():
                puntos, _, conflicto = _puntuar_progenitor(fila, hijo, tipo, nombres, apellidos, ancla, ap_mat_extra)
                if not conflicto:
                    mejor = max(mejor, puntos)
            if mejor >= config.FAMILIA_UMBRAL_ALTA:
                break

    return list(candidatos.values())


def _puntuar_progenitor(
    candidato: dict,
    hijo: dict,
    tipo: str,
    nombres_reg: list[str],
    apellidos_reg: list[str],
    ancla: str,
    ap_mat_extra: str,
) -> tuple[int, list[dict], bool]:
    """Puntúa un candidato a progenitor. Devuelve (puntos, evidencia, conflicto)."""
    if str(candidato.get("dni") or "") == str(hijo.get("dni") or ""):
        return -999, [], True

    ap_pat_cand = normalizar(candidato.get("ap_pat"))
    ap_mat_cand = normalizar(candidato.get("ap_mat"))
    puntos = 0
    evidencias: list[dict] = []

    if ancla:
        if ap_pat_cand != ancla:
            return -999, [], True
        puntos += 30
        evidencias.append(_evidencia("apellido_heredado", "Apellido paterno heredado coincide", 30))

    if ap_mat_extra:
        if ap_mat_cand == ap_mat_extra:
            puntos += 10
            evidencias.append(_evidencia("apellido_materno_extra", "Segundo apellido del campo coincide", 10))
        elif ap_mat_cand:
            puntos -= 10
            evidencias.append(_evidencia("apellido_materno_distinto", "Segundo apellido no coincide", -10))

    puntos_nombre, conflicto, ev_nombre = _puntuar_nombre_registrado(
        " ".join(nombres_reg),
        candidato.get("nombres"),
        candidato.get("ap_pat"),
        candidato.get("ap_mat"),
        ancla,
    )
    puntos += puntos_nombre
    evidencias.extend(ev_nombre)
    if conflicto and puntos_nombre <= 0:
        return puntos, evidencias, True

    sexo_esperado = "1" if tipo == "padre" else "2"
    sexo_cand = str(candidato.get("sexo") or "")
    if sexo_cand in {"1", "2", "Masculino", "Femenino"}:
        if sexo_cand in {sexo_esperado, "Masculino" if tipo == "padre" else "Femenino"}:
            puntos += 5
            evidencias.append(_evidencia("sexo", "Sexo compatible", 5))
        else:
            return -999, [], True

    diferencia = _anios_entre(candidato.get("fecha_nac"), hijo.get("fecha_nac"))
    if diferencia is not None:
        if diferencia < 13 or diferencia > 85:
            return -999, [], True
        optimo = (18, 55) if tipo == "padre" else (16, 48)
        if optimo[0] <= diferencia <= optimo[1]:
            puntos += 8
            evidencias.append(_evidencia("edad_optima", "Edad compatible con la procreación", 8))
        else:
            puntos += 4
            evidencias.append(_evidencia("edad_valida", "Edad biológicamente posible", 4))

    puntos_geo, ev_geo = _evidencia_geografica(candidato, hijo)
    puntos += puntos_geo
    evidencias.extend(ev_geo)

    puntos_dir, ev_dir = _evidencia_direccion(candidato, hijo)
    puntos += puntos_dir
    evidencias.extend(ev_dir)

    puntos_doc, ev_doc = _evidencia_documental(candidato, hijo)
    puntos += puntos_doc
    evidencias.extend(ev_doc)

    if not _nombre_es_fuerte(ev_nombre) and not any(
        e.get("codigo") == "misma_direccion" for e in ev_dir
    ):
        puntos = min(puntos, config.FAMILIA_UMBRAL_MEDIA - 1)
        evidencias.append(
            _evidencia(
                "progenitor_evidencia_debil",
                "Nombre del progenitor incompleto: requiere verificación",
                0,
            )
        )

    return max(0, min(100, puntos)), evidencias, False


def _resumen_candidato(candidato: dict, puntos: int, evidencias: list[dict]) -> dict:
    return {
        "dni": candidato.get("dni"),
        "nombres": candidato.get("nombres"),
        "ap_pat": candidato.get("ap_pat"),
        "ap_mat": candidato.get("ap_mat"),
        "fecha_nac": str(candidato.get("fecha_nac")) if candidato.get("fecha_nac") else None,
        "sexo": candidato.get("sexo"),
        "confianza": int(puntos),
        "nivel_confianza": _nivel_confianza(puntos),
        "evidencia": evidencias,
    }


def _nodo(
    fila: dict,
    puntos: float,
    evidencias: list[dict],
    *,
    tipo_relacion: str | None = None,
    candidatos: list[dict] | None = None,
) -> dict:
    fecha_nac = fila.get("fecha_nac")
    return {
        "dni": fila.get("dni"),
        "nombres": fila.get("nombres"),
        "ap_pat": fila.get("ap_pat"),
        "ap_mat": fila.get("ap_mat"),
        "sexo": fila.get("sexo"),
        "edad_anios": fila.get("edad_anios"),
        "fecha_nac": str(fecha_nac) if fecha_nac else None,
        "est_civil": fila.get("est_civil"),
        "padre": fila.get("padre"),
        "madre": fila.get("madre"),
        "direccion": fila.get("direccion"),
        "ubigeo_nac": fila.get("ubigeo_nac"),
        "ubigeo_dir": fila.get("ubigeo_dir"),
        "encontrado": True,
        "confianza": int(puntos),
        "nivel_confianza": _nivel_confianza(puntos),
        "evidencia": evidencias,
        "candidatos": candidatos or [],
        "tipo_relacion": tipo_relacion,
    }


def _nodo_placeholder(
    texto: Any,
    sexo: str | None,
    apellido_ancla: Any,
    candidatos: list[dict] | None,
    puntos: float,
    tipo_relacion: str | None = None,
) -> dict | None:
    if not texto or not str(texto).strip():
        return None
    nombres, apellidos = separar_nombres_apellidos(texto, apellido_ancla)
    return {
        "dni": None,
        "nombres": " ".join(nombres) if nombres else None,
        "ap_pat": apellidos[0] if apellidos else (normalizar(apellido_ancla) or None),
        "ap_mat": apellidos[1] if len(apellidos) > 1 else None,
        "sexo": sexo,
        "edad_anios": None,
        "fecha_nac": None,
        "est_civil": None,
        "padre": None,
        "madre": None,
        "direccion": None,
        "ubigeo_nac": None,
        "ubigeo_dir": None,
        "encontrado": False,
        "confianza": int(max(0, puntos)),
        "nivel_confianza": _nivel_confianza(max(0, puntos)),
        "evidencia": [],
        "candidatos": candidatos or [],
        "tipo_relacion": tipo_relacion,
    }


def _resolver_progenitor(conn, hijo: dict, tipo: str) -> dict:
    """Devuelve el mejor progenitor, sus alternativas y la confianza."""
    texto = hijo.get("padre") if tipo == "padre" else hijo.get("madre")
    ancla = normalizar(hijo.get("ap_pat") if tipo == "padre" else hijo.get("ap_mat"))
    if not texto or not str(texto).strip():
        return {"nodo": None, "candidatos": [], "confianza": 0, "evidencia": []}

    nombres, apellidos = separar_nombres_apellidos(texto, ancla)
    ap_mat_extra = apellidos[1] if len(apellidos) > 1 else ""
    filas = _buscar_candidatos_progenitor(conn, hijo, tipo)

    puntuados: list[tuple[int, dict, list[dict]]] = []
    for fila in filas:
        puntos, evidencias, conflicto = _puntuar_progenitor(fila, hijo, tipo, nombres, apellidos, ancla, ap_mat_extra)
        if conflicto or puntos < 0:
            continue
        puntuados.append((puntos, fila, evidencias))

    puntuados.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("fecha_nac") or "9999-12-31"),
        )
    )
    if not puntuados:
        return {"nodo": None, "candidatos": [], "confianza": 0, "evidencia": []}

    mejores = puntuados[:10]
    candidatos = [_resumen_candidato(fila, puntos, evidencias) for puntos, fila, evidencias in mejores]
    mejor_puntos, mejor_fila, mejor_evidencia = mejores[0]

    nodo = None
    if mejor_puntos >= config.FAMILIA_UMBRAL_MEDIA:
        nodo = _nodo(
            mejor_fila,
            mejor_puntos,
            mejor_evidencia,
            tipo_relacion=tipo,
            candidatos=candidatos[1:],
        )
    return {
        "nodo": nodo,
        "candidatos": candidatos,
        "confianza": mejor_puntos,
        "evidencia": mejor_evidencia,
    }


# ── Hermanos ────────────────────────────────────────────────────────────


def _buscar_candidatos_hermanos(conn, persona: dict, limite: int) -> list[dict]:
    ap_pat = normalizar(persona.get("ap_pat"))
    ap_mat = normalizar(persona.get("ap_mat"))
    padre_txt = persona.get("padre")
    madre_txt = persona.get("madre")
    dni = str(persona.get("dni") or "")
    fecha = _fecha(persona.get("fecha_nac"))

    candidatos: dict[str, dict] = {}

    def _agregar(filas: list[dict]) -> None:
        for fila in filas:
            clave = str(fila.get("dni") or "")
            if clave and clave != dni and clave not in candidatos:
                candidatos[clave] = fila

    rango = ""
    params_rango: dict[str, Any] = {}
    if fecha:
        rango = "AND (p.fecha_nac IS NULL OR p.fecha_nac BETWEEN :fecha_min AND :fecha_max)"
        params_rango = {
            "fecha_min": (fecha - timedelta(days=int(60 * 365.25))).isoformat(),
            "fecha_max": (fecha + timedelta(days=int(60 * 365.25))).isoformat(),
        }

    # 1. Hermanos completos: ambos apellidos heredados.
    if ap_pat and ap_mat:
        sql = f"""
            SELECT {_CAMPOS_CANDIDATO}
            FROM personas p
            WHERE p.search_vector @@ to_tsquery('simple', :tsq)
              AND immutable_unaccent(lower(p.ap_pat)) = :ap_pat
              AND immutable_unaccent(lower(p.ap_mat)) = :ap_mat
              AND p.dni <> :dni
              {rango}
            LIMIT :limite
        """
        _agregar(
            _query(
                conn,
                sql,
                {
                    "tsq": f"{ap_pat} & {ap_mat}",
                    "ap_pat": ap_pat,
                    "ap_mat": ap_mat,
                    "dni": dni,
                    "limite": limite,
                    **params_rango,
                },
                timeout_ms=4000,
                strict=False,
            )
        )

    # 2. Medio hermanos por padre: apellido paterno + nombre del padre.
    if ap_pat and padre_txt:
        nombre_padre = tokenizar(padre_txt)[0] if tokenizar(padre_txt) else ""
        if nombre_padre:
            sql = f"""
                SELECT {_CAMPOS_CANDIDATO}
                FROM personas p
                WHERE p.search_vector @@ to_tsquery('simple', :tsq)
                  AND immutable_unaccent(lower(p.ap_pat)) = :ap_pat
                  AND p.dni <> :dni
                  AND p.padre IS NOT NULL AND btrim(p.padre) <> ''
                  AND (
                      immutable_unaccent(lower(p.padre)) LIKE :nombre || '%'
                  )
                  {rango}
                LIMIT :limite
            """
            _agregar(
                _query(
                    conn,
                    sql,
                    {
                        "tsq": ap_pat,
                        "ap_pat": ap_pat,
                        "dni": dni,
                        "nombre": nombre_padre,
                        "limite": limite,
                        **params_rango,
                    },
                    timeout_ms=4000,
                    strict=False,
                )
            )

    # 3. Medio hermanos por madre: apellido materno + nombre de la madre.
    if ap_mat and madre_txt:
        nombre_madre = tokenizar(madre_txt)[0] if tokenizar(madre_txt) else ""
        if nombre_madre:
            sql = f"""
                SELECT {_CAMPOS_CANDIDATO}
                FROM personas p
                WHERE p.search_vector @@ to_tsquery('simple', :tsq)
                  AND immutable_unaccent(lower(p.ap_mat)) = :ap_mat
                  AND p.dni <> :dni
                  AND p.madre IS NOT NULL AND btrim(p.madre) <> ''
                  AND (
                      immutable_unaccent(lower(p.madre)) LIKE :nombre || '%'
                  )
                  {rango}
                LIMIT :limite
            """
            _agregar(
                _query(
                    conn,
                    sql,
                    {
                        "tsq": ap_mat,
                        "ap_mat": ap_mat,
                        "dni": dni,
                        "nombre": nombre_madre,
                        "limite": limite,
                        **params_rango,
                    },
                    timeout_ms=4000,
                    strict=False,
                )
            )

    # 4. Sin campos de padres: solo apellidos (último recurso).
    if not candidatos:
        ancla = ap_pat or ap_mat
        if ancla:
            sql = f"""
                SELECT {_CAMPOS_CANDIDATO}
                FROM personas p
                WHERE p.search_vector @@ to_tsquery('simple', :tsq)
                  AND p.dni <> :dni
                  {rango}
                LIMIT :limite
            """
            _agregar(
                _query(
                    conn,
                    sql,
                    {"tsq": ancla, "dni": dni, "limite": limite, **params_rango},
                    timeout_ms=4000,
                    strict=False,
                )
            )

    return list(candidatos.values())


def _puntuar_hermano(
    candidato: dict,
    persona: dict,
    padre_txt: Any,
    madre_txt: Any,
) -> tuple[int, list[dict], str | None, bool]:
    """Puntúa un candidato a hermano/a."""
    if str(candidato.get("dni") or "") == str(persona.get("dni") or ""):
        return -999, [], None, True

    ap_pat_titular = normalizar(persona.get("ap_pat"))
    ap_mat_titular = normalizar(persona.get("ap_mat"))
    ap_pat_cand = normalizar(candidato.get("ap_pat"))
    ap_mat_cand = normalizar(candidato.get("ap_mat"))

    coincide_pat = bool(ap_pat_titular and ap_pat_cand == ap_pat_titular)
    coincide_mat = bool(ap_mat_titular and ap_mat_cand == ap_mat_titular)

    puntos = 0
    evidencias: list[dict] = []
    if coincide_pat:
        puntos += 15
        evidencias.append(_evidencia("apellido_paterno", "Comparte apellido paterno", 15))
    if coincide_mat:
        puntos += 15
        evidencias.append(_evidencia("apellido_materno", "Comparte apellido materno", 15))

    padre_puntos, padre_conflicto, padre_ev = _compatibilidad_campos_progenitor(padre_txt, candidato.get("padre"))
    madre_puntos, madre_conflicto, madre_ev = _compatibilidad_campos_progenitor(madre_txt, candidato.get("madre"))

    # Un progenitor puede faltar o ser distinto (medio hermano). Solo se
    # descarta cuando ambos campos existen y ambos son incompatibles.
    # Un solo token coincidente (p. ej. "MANUEL" frente a "MANUEL JESUS")
    # cuenta como indicio, no como confirmación: se combina con el otro
    # progenitor, la edad, la geografía o el domicilio.
    padre_ok = padre_puntos >= 10 and not padre_conflicto
    madre_ok = madre_puntos >= 10 and not madre_conflicto
    if padre_txt and candidato.get("padre") and madre_txt and candidato.get("madre"):
        if padre_conflicto and madre_conflicto:
            return -999, [], None, True
    if padre_txt and candidato.get("padre") and padre_conflicto and not madre_ok:
        return -999, [], None, True
    if madre_txt and candidato.get("madre") and madre_conflicto and not padre_ok:
        return -999, [], None, True

    if padre_ok:
        puntos += padre_puntos
        evidencias.extend(padre_ev)
    if madre_ok:
        puntos += madre_puntos
        evidencias.extend(madre_ev)

    # El tipo de relación se decide al final: un progenitor del que solo
    # conocemos el primer nombre no basta para afirmar una media hermandad.
    if padre_ok and madre_ok:
        puntos += 20
        evidencias.append(_evidencia("ambos_progenitores", "Ambos progenitores coinciden", 20))
    elif padre_ok or madre_ok:
        puntos += 5

    diferencia = _anios_entre(candidato.get("fecha_nac"), persona.get("fecha_nac"))
    if diferencia is not None:
        diferencia = abs(diferencia)
        if diferencia > 60:
            return -999, [], None, True
        if diferencia <= 10:
            puntos += 5
            evidencias.append(_evidencia("edad_cercana", "Edad muy cercana", 5))
        elif diferencia <= 20:
            puntos += 3
            evidencias.append(_evidencia("edad_compatible", "Edad compatible entre hermanos", 3))
        elif diferencia <= 35:
            puntos += 1

    puntos_geo, ev_geo = _evidencia_geografica(candidato, persona)
    puntos += min(puntos_geo, 10)
    evidencias.extend(ev_geo)

    puntos_dir, ev_dir = _evidencia_direccion(candidato, persona)
    puntos += min(puntos_dir, 8)
    evidencias.extend(ev_dir)

    puntos_doc, ev_doc = _evidencia_documental(candidato, persona)
    puntos += puntos_doc
    evidencias.extend(ev_doc)

    padre_fuerte = padre_ok and padre_puntos >= 20
    madre_fuerte = madre_ok and madre_puntos >= 20
    apoyo_contexto = min(puntos_geo, 10) + min(puntos_dir, 8)

    if padre_ok and madre_ok:
        tipo = "hermano_completo" if (padre_fuerte and madre_fuerte) else "hermano_probable"
        if tipo == "hermano_probable":
            puntos = min(puntos, config.FAMILIA_UMBRAL_MEDIA - 1)
            evidencias.append(
                _evidencia(
                    "progenitores_debiles",
                    "Uno o ambos nombres de los progenitores son incompletos",
                    0,
                )
            )
    elif padre_ok:
        confirmado = (padre_fuerte and apoyo_contexto >= 4) or apoyo_contexto >= 10
        tipo = "medio_hermano_paterno" if confirmado else "hermano_probable"
    elif madre_ok:
        confirmado = (madre_fuerte and apoyo_contexto >= 4) or apoyo_contexto >= 10
        tipo = "medio_hermano_materno" if confirmado else "hermano_probable"
    else:
        tipo = "hermano_probable"

    if tipo == "hermano_probable":
        # No presentar como confianza media una relación sustentada solo en
        # el primer nombre de un progenitor o en apellidos compartidos.
        # Si además no hay respaldo geográfico, se omite: de lo contrario
        # cualquier homónimo del padre aparecería como medio hermano.
        minimo_contexto = 4 if (padre_ok or madre_ok) else 6
        if apoyo_contexto < minimo_contexto:
            return -999, [], "debil_sin_contexto", True
        puntos = min(puntos, config.FAMILIA_UMBRAL_MEDIA - 1)
        evidencias.append(
            _evidencia(
                "evidencia_debil",
                "Evidencia insuficiente: relación probable, requiere verificación",
                0,
            )
        )

    return max(0, min(100, puntos)), evidencias, tipo, False


def _buscar_hermanos(conn, persona: dict, limite: int) -> tuple[list[dict], bool, int]:
    padre_txt = persona.get("padre")
    madre_txt = persona.get("madre")
    filas = _buscar_candidatos_hermanos(conn, persona, max(limite * 3, 200))

    puntuados: list[tuple[int, dict, list[dict], str | None]] = []
    omitidos_debiles = 0
    for fila in filas:
        puntos, evidencias, tipo, conflicto = _puntuar_hermano(fila, persona, padre_txt, madre_txt)
        if conflicto:
            if tipo == "debil_sin_contexto":
                omitidos_debiles += 1
            continue
        umbral = 30 if tipo == "hermano_probable" else config.FAMILIA_UMBRAL_MEDIA
        if puntos < umbral:
            continue
        puntuados.append((puntos, fila, evidencias, tipo))

    # Primero los hermanos con evidencia suficiente; dentro de cada grupo,
    # los de mayor confianza y luego los de nacimiento más antiguo.
    puntuados.sort(
        key=lambda item: (
            0 if item[3] != "hermano_probable" else 1,
            -item[0],
            str(item[1].get("fecha_nac") or "9999-12-31"),
        )
    )
    truncado = len(puntuados) > limite
    nodos = [
        _nodo(fila, puntos, evidencias, tipo_relacion=tipo) for puntos, fila, evidencias, tipo in puntuados[:limite]
    ]
    return nodos, truncado, omitidos_debiles


# ── Hijos ───────────────────────────────────────────────────────────────


def _modos_hijos(persona: dict) -> list[tuple[str, str]]:
    """Devuelve (campo_progenitor, columna_apellido) según el sexo."""
    sexo = normalizar(persona.get("sexo"))
    ap_pat = normalizar(persona.get("ap_pat"))
    if not ap_pat:
        return []
    if sexo in {"1", "masculino", "m"}:
        return [("padre", "ap_pat")]
    if sexo in {"2", "femenino", "f"}:
        return [("madre", "ap_mat")]
    # Sexo desconocido: se prueban ambas vías y se deduplica.
    return [("padre", "ap_pat"), ("madre", "ap_mat")]


def _buscar_candidatos_hijos(conn, persona: dict, limite: int) -> list[dict]:
    nombre = tokenizar(persona.get("nombres"))
    if not nombre:
        return []
    primer_nombre = nombre[0]
    fecha_persona = _fecha(persona.get("fecha_nac"))
    dni = str(persona.get("dni") or "")

    rango = ""
    params_rango: dict[str, Any] = {}
    if fecha_persona:
        rango = "AND (p.fecha_nac IS NULL OR p.fecha_nac BETWEEN :fecha_min AND :fecha_max)"
        params_rango = {
            "fecha_min": (fecha_persona + timedelta(days=int(13 * 365.25))).isoformat(),
            "fecha_max": (fecha_persona + timedelta(days=int(70 * 365.25))).isoformat(),
        }

    candidatos: dict[str, dict] = {}
    for campo, columna in _modos_hijos(persona):
        ancla = normalizar(persona.get("ap_pat"))
        if not ancla:
            continue
        sql = f"""
            SELECT {_CAMPOS_CANDIDATO}
            FROM personas p
            WHERE p.search_vector @@ to_tsquery('simple', :tsq)
              AND immutable_unaccent(lower(p.{columna})) = :ancla
              AND p.dni <> :dni
              AND p.{campo} IS NOT NULL AND btrim(p.{campo}) <> ''
              AND (
                  immutable_unaccent(lower(p.{campo})) LIKE :nombre || '%'
              )
              {rango}
            LIMIT :limite
        """
        filas = _query(
            conn,
            sql,
            {
                "tsq": ancla,
                "ancla": ancla,
                "dni": dni,
                "nombre": primer_nombre,
                "limite": limite,
                **params_rango,
            },
            timeout_ms=4000,
            strict=False,
        )
        for fila in filas:
            clave = str(fila.get("dni") or "")
            if not clave or clave == dni:
                continue
            existente = candidatos.get(clave)
            if existente is None:
                fila["_modos"] = [(campo, columna)]
                candidatos[clave] = fila
            else:
                modos = existente.setdefault("_modos", [])
                if (campo, columna) not in modos:
                    modos.append((campo, columna))
    return list(candidatos.values())


def _puntuar_hijo(
    candidato: dict,
    persona: dict,
    campo: str,
    columna: str,
) -> tuple[int, list[dict], bool, bool]:
    if str(candidato.get("dni") or "") == str(persona.get("dni") or ""):
        return -999, [], True, False

    ancla = normalizar(persona.get("ap_pat"))
    apellido_hijo = normalizar(candidato.get(columna))
    if ancla and apellido_hijo != ancla:
        return -999, [], True, False

    puntos = 25
    evidencias = [_evidencia("apellido_heredado_hijo", "Apellido heredado del progenitor", 25)]

    # El campo de filiación del hijo suele traer solo nombres de pila. En
    # modo estricto, un nombre incompleto no confirma por sí solo la
    # relación: se exige además edad, geografía o domicilio compatible.
    puntos_nombre, conflicto, ev_nombre = _puntuar_nombre_registrado(
        candidato.get(campo),
        persona.get("nombres"),
        persona.get("ap_pat"),
        persona.get("ap_mat"),
        ancla,
        estricto=True,
    )
    if conflicto and puntos_nombre <= 0:
        return -999, [], True, False
    puntos += puntos_nombre
    evidencias.extend(ev_nombre)

    codigos_nombre = {e.get("codigo") for e in ev_nombre}
    nombre_fuerte = bool(codigos_nombre & {"nombre_exacto", "nombre_ordenado"})

    diferencia = _anios_entre(persona.get("fecha_nac"), candidato.get("fecha_nac"))
    if diferencia is not None:
        if diferencia < 13 or diferencia > 70:
            return -999, [], True, False
        if 18 <= diferencia <= 45:
            puntos += 10
            evidencias.append(_evidencia("edad_reproductiva", "Edad reproductiva compatible", 10))
        elif 13 <= diferencia <= 55:
            puntos += 5
            evidencias.append(_evidencia("edad_posible", "Edad biológicamente posible", 5))

    puntos_geo, ev_geo = _evidencia_geografica(candidato, persona)
    puntos += min(puntos_geo, 10)
    evidencias.extend(ev_geo)

    puntos_dir, ev_dir = _evidencia_direccion(candidato, persona)
    puntos += min(puntos_dir, 8)
    evidencias.extend(ev_dir)

    puntos_doc, ev_doc = _evidencia_documental(candidato, persona)
    puntos += puntos_doc
    evidencias.extend(ev_doc)

    apoyo_contexto = min(puntos_geo, 10) + min(puntos_dir, 8)
    probable = False
    if not nombre_fuerte:
        # Un nombre en otro orden o incompleto, sin geografía ni domicilio
        # que lo respalde, no permite afirmar la filiación. Se descarta en
        # lugar de llenar el árbol de homónimos.
        if apoyo_contexto < 4:
            return -999, [], True, False
        probable = True
        puntos = min(puntos, config.FAMILIA_UMBRAL_MEDIA - 1)
        evidencias.append(
            _evidencia(
                "evidencia_debil_hijo",
                "Nombre incompleto o en otro orden: filiación probable, requiere verificación",
                0,
            )
        )

    return max(0, min(100, puntos)), evidencias, False, probable


def _buscar_hijos(
    conn,
    persona: dict,
    limite: int,
) -> tuple[list[dict], bool]:
    filas = _buscar_candidatos_hijos(conn, persona, max(limite * 3, 200))
    puntuados: list[tuple[int, dict, list[dict], str]] = []

    for fila in filas:
        modos = fila.get("_modos") or []
        if not modos:
            continue
        mejor: tuple[int, list[dict], str] | None = None
        for campo, columna in modos:
            puntos, evidencias, conflicto, probable = _puntuar_hijo(fila, persona, campo, columna)
            umbral = 30 if probable else config.FAMILIA_UMBRAL_MEDIA
            if conflicto or puntos < umbral:
                continue
            base = "hija" if normalizar(fila.get("sexo")) in {"2", "femenino", "f"} else "hijo"
            tipo = f"{base}_probable" if probable else base
            if mejor is None or puntos > mejor[0]:
                mejor = (puntos, evidencias, tipo)
        if mejor is not None:
            puntuados.append((mejor[0], fila, mejor[1], mejor[2]))

    # Primero los hijos con evidencia suficiente; los probables quedan al
    # final para no mezclarlos con filiaciones confirmadas.
    puntuados.sort(
        key=lambda item: (
            0 if not str(item[3]).endswith("_probable") else 1,
            -item[0],
            str(item[1].get("fecha_nac") or "9999-12-31"),
        )
    )
    truncado = len(puntuados) > limite
    nodos = [
        _nodo(fila, puntos, evidencias, tipo_relacion=tipo) for puntos, fila, evidencias, tipo in puntuados[:limite]
    ]
    return nodos, truncado


# ── Árbol ───────────────────────────────────────────────────────────────


def _resolver_y_colocar(
    resultado: dict,
    clave: str,
    resolucion: dict,
    texto: Any,
    sexo: str | None,
    ancla: Any,
    tipo_relacion: str,
) -> None:
    if resolucion.get("nodo"):
        resultado[clave] = resolucion["nodo"]
    else:
        resultado[clave] = _nodo_placeholder(
            texto,
            sexo,
            ancla,
            resolucion.get("candidatos") or [],
            resolucion.get("confianza") or 0,
            tipo_relacion,
        )


def construir_arbol(dni: str, limite: int | None = None) -> dict | None:
    """Construye el árbol genealógico con confianza, evidencia y alternativas.

    Las ramas independientes (progenitores, hermanos, hijos) se ejecutan en
    paralelo con conexiones propias y un pool acotado; antes eran ~19 consultas
    secuenciales que podían agotar el pool de SQLAlchemy con pocas peticiones.
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.sql.queries import PERSONA_POR_DNI

    limite = max(1, min(int(limite or config.FAMILIA_LIMITE_DEFAULT), config.FAMILIA_LIMITE_MAX))

    with engine.connect() as conn:
        filas = _query(conn, PERSONA_POR_DNI, {"dni": dni}, timeout_ms=7000)
    if not filas:
        return None
    persona = filas[0]

    def _with_conn(fn, *args):
        with engine.connect() as conn:
            return fn(conn, *args)

    resultado: dict[str, Any] = {
        "persona": _nodo(
            persona,
            100,
            [_evidencia("titular", "Persona titular del árbol", 100)],
            tipo_relacion="titular",
        ),
        "padre": None,
        "madre": None,
        "abuelo_paterno": None,
        "abuela_paterna": None,
        "abuelo_materno": None,
        "abuela_materna": None,
        "hermanos": [],
        "hijos": [],
    }

    # Etapa 1: todo lo que depende solo del titular.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="familia") as pool:
        f_padre = pool.submit(_with_conn, _resolver_progenitor, persona, "padre")
        f_madre = pool.submit(_with_conn, _resolver_progenitor, persona, "madre")
        f_hermanos = pool.submit(_with_conn, _buscar_hermanos, persona, limite)
        f_hijos = pool.submit(_with_conn, _buscar_hijos, persona, limite)
        padre_res = f_padre.result()
        madre_res = f_madre.result()
        hermanos, hermanos_truncados, hermanos_debiles = f_hermanos.result()
        hijos, hijos_truncados = f_hijos.result()

    _resolver_y_colocar(
        resultado, "padre", padre_res, persona.get("padre"), "Masculino",
        persona.get("ap_pat"), "padre",
    )
    _resolver_y_colocar(
        resultado, "madre", madre_res, persona.get("madre"), "Femenino",
        persona.get("ap_mat"), "madre",
    )

    padre_nodo = resultado.get("padre")
    madre_nodo = resultado.get("madre")

    # Etapa 2: abuelos, que dependen de los progenitores ya resueltos.
    tareas_abuelos = []
    if padre_nodo and padre_nodo.get("encontrado"):
        tareas_abuelos.append(("abuelo_paterno", padre_nodo, "padre", "Masculino"))
        tareas_abuelos.append(("abuela_paterna", padre_nodo, "madre", "Femenino"))
    if madre_nodo and madre_nodo.get("encontrado"):
        tareas_abuelos.append(("abuelo_materno", madre_nodo, "padre", "Masculino"))
        tareas_abuelos.append(("abuela_materna", madre_nodo, "madre", "Femenino"))

    if tareas_abuelos:
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="abuelos") as pool:
            futuros = {
                clave: pool.submit(_with_conn, _resolver_progenitor, nodo, tipo)
                for clave, nodo, tipo, _sexo in tareas_abuelos
            }
            for clave, nodo, _tipo, sexo in tareas_abuelos:
                resolucion = futuros[clave].result()
                ancla = nodo.get("ap_pat") if sexo == "Masculino" else nodo.get("ap_mat")
                _resolver_y_colocar(
                    resultado, clave, resolucion, nodo.get("padre" if sexo == "Masculino" else "madre"),
                    sexo, ancla, clave,
                )

    resultado["hermanos"] = hermanos
    resultado["hijos"] = hijos

    advertencias: list[str] = []
    if not (persona.get("padre") or persona.get("madre")):
        advertencias.append(
            "No hay nombres de progenitores registrados: la búsqueda de "
            "hermanos se basa solo en apellidos y es menos precisa."
        )
    if persona.get("padre") and not (padre_nodo and padre_nodo.get("encontrado")):
        advertencias.append("Padre no confirmado con evidencia suficiente; revisa los candidatos.")
    if persona.get("madre") and not (madre_nodo and madre_nodo.get("encontrado")):
        advertencias.append("Madre no confirmada con evidencia suficiente; revisa los candidatos.")
    probables = sum(1 for h in hermanos if h.get("tipo_relacion") == "hermano_probable")
    if probables:
        advertencias.append(
            f"{probables} hermano(s) son probables (baja confianza): "
            "solo se comparten apellidos o parte del nombre de un progenitor."
        )
    if hermanos_debiles:
        advertencias.append(
            f"Se omitieron {hermanos_debiles} posibles medios hermanos sin "
            "respaldo geográfico suficiente para evitar homónimos."
        )
    hijos_probables = sum(1 for h in hijos if str(h.get("tipo_relacion") or "").endswith("_probable"))
    if hijos_probables:
        advertencias.append(
            f"{hijos_probables} hijo(s) son probables (baja confianza): "
            "el nombre registrado del progenitor está incompleto o en otro orden."
        )
    if hermanos_truncados:
        advertencias.append(f"Se muestran los {limite} hermanos con mayor confianza; hay más candidatos.")
    if hijos_truncados:
        advertencias.append(f"Se muestran los {limite} hijos con mayor confianza; hay más candidatos.")
    if not _fecha(persona.get("fecha_nac")):
        advertencias.append("La persona no tiene fecha de nacimiento: la validación de edad es limitada.")

    resultado["meta"] = {
        "version": "2.0",
        "limite_por_relacion": limite,
        "umbral_alta": config.FAMILIA_UMBRAL_ALTA,
        "umbral_media": config.FAMILIA_UMBRAL_MEDIA,
        "candidatos_analizados_por_relacion": config.FAMILIA_CANDIDATOS,
        "advertencias": advertencias,
    }
    return resultado
