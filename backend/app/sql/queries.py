SEXO_EXPR = """
    CASE
        WHEN sexo::text = '1' THEN 'Masculino'
        WHEN sexo::text = '2' THEN 'Femenino'
        ELSE COALESCE(sexo::text, '-')
    END
"""

EDAD_COLS = """
    EXTRACT(YEAR FROM age(current_date, fecha_nac))::int AS edad_anios,
    EXTRACT(MONTH FROM age(current_date, fecha_nac))::int AS edad_meses,
    EXTRACT(DAY FROM age(current_date, fecha_nac))::int AS edad_dias,
    CONCAT(
        EXTRACT(YEAR FROM age(current_date, fecha_nac))::int, ' años, ',
        EXTRACT(MONTH FROM age(current_date, fecha_nac))::int, ' meses, ',
        EXTRACT(DAY FROM age(current_date, fecha_nac))::int, ' días'
    ) AS edad_texto
"""

PERSONA_POR_DNI = f"""
    SELECT
        dni,
        ap_pat,
        ap_mat,
        nombres,
        padre,
        madre,
        fecha_nac,
        fch_emision,
        fch_inscripcion,
        fch_caducidad,
        direccion,
        ubigeo_nac,
        ubigeo_dir,
        {SEXO_EXPR} AS sexo,
        est_civil,
        {EDAD_COLS}
    FROM personas
    WHERE dni = :dni
    LIMIT 1
"""

NC_EXPR = "build_nombre_completo(nombres, ap_pat, ap_mat)"
NC_BUSQUEDA_EXPR = "build_nombre_busqueda(ap_pat, ap_mat, nombres)"

MAX_CANDIDATOS = 80   # tope base de candidatas para ranking ultra-rápido (<15ms)
BUCKET_SIZE = 500     # filas base por bucket (early-exit del index scan)

PRE_RANK_EXPR = """
    (
        CASE WHEN {NC} = :q_lower OR {NC_BUSQ} = :q_lower THEN 10000
             WHEN {NC} LIKE :q_prefix OR {NC_BUSQ} LIKE :q_prefix THEN 5000
             ELSE 0
        END
        + CASE WHEN lower(p.ap_pat) = :q_lower THEN 3500 ELSE 0 END
        + CASE WHEN lower(p.nombres) = :q_lower THEN 3000 ELSE 0 END
        + CASE WHEN lower(p.ap_mat) = :q_lower THEN 2000 ELSE 0 END
        + CASE WHEN lower(p.ap_pat) LIKE :q_prefix THEN 800 ELSE 0 END
        + CASE WHEN lower(p.nombres) LIKE :q_prefix THEN 500 ELSE 0 END
        + CASE WHEN :w1 != '' AND lower(p.ap_pat) = :w1 THEN 1200 ELSE 0 END
        + CASE WHEN :w2 != '' AND lower(p.ap_mat) = :w2 THEN 1000 ELSE 0 END
        + CASE WHEN :w3 != '' AND lower(p.nombres) LIKE :w3 || '%' THEN 800 ELSE 0 END
        + CASE WHEN :w1 != '' AND lower(p.nombres) = :w1 THEN 900 ELSE 0 END
        + CASE WHEN :w2 != '' AND lower(p.ap_pat) = :w2 THEN 700 ELSE 0 END
        + GREATEST(
            COALESCE(similarity({NC}, :q_lower), 0),
            COALESCE(similarity({NC_BUSQ}, :q_lower), 0)
        ) * 300
    ) AS pre_rank
"""


def _bucket_sql(col: str) -> str:
    """Bucket por componente (1 palabra): prefix match con early-exit.

    Requiere indice btree sobre lower(col) con text_pattern_ops.
    Devuelve filas ordenadas por dni (no por ranking); el merge y el sort
    se hacen en Python con BUCKET_SIZE filas por bucket.
    """
    return f"""
        SELECT
            p.dni, {NC_EXPR} AS nc,
            {PRE_RANK_EXPR.format(NC=NC_EXPR, NC_BUSQ=NC_BUSQUEDA_EXPR)}
        FROM personas p
        WHERE lower({col}) LIKE :q_prefix
        ORDER BY p.dni
        LIMIT :bucket_size
    """


BUSCAR_BUCKET_AP_PAT = _bucket_sql("ap_pat")
BUSCAR_BUCKET_AP_MAT = _bucket_sql("ap_mat")
BUSCAR_BUCKET_NOMBRES = _bucket_sql("nombres")

BUSCAR_BUCKETS = [
    BUSCAR_BUCKET_AP_PAT,
    BUSCAR_BUCKET_AP_MAT,
    BUSCAR_BUCKET_NOMBRES,
]

BUSCAR_DNI = f"""
    SELECT
        p.dni, {NC_EXPR} AS nc,
        {PRE_RANK_EXPR.format(NC=NC_EXPR, NC_BUSQ=NC_BUSQUEDA_EXPR)}
    FROM personas p
    WHERE p.dni = :q
    ORDER BY p.dni
    LIMIT 1
"""

BUSCAR_FONETICO = f"""
    SELECT
        p.dni, {NC_EXPR} AS nc,
        {PRE_RANK_EXPR.format(NC=NC_EXPR, NC_BUSQ=NC_BUSQUEDA_EXPR)}
    FROM personas p
    WHERE soundex(immutable_unaccent(p.ap_pat)) = soundex(:w1)
       OR soundex(immutable_unaccent(p.nombres)) = soundex(:w1)
    ORDER BY p.dni
    LIMIT :bucket_size
"""


def _candidatos_sql(where_branch: str, with_tsqs: bool) -> str:
    """Pasada de candidatos ordenada por pre_rank: devuelve top :cand_limit."""
    tsqs = """
        tsqs AS (
            SELECT
                websearch_to_tsquery('simple', immutable_unaccent(:q)) AS ws_q,
                phraseto_tsquery('simple', immutable_unaccent(:q)) AS phr_q
        ),
    """
    return f"""
        WITH {tsqs if with_tsqs else ""}
        base AS (
            SELECT
                p.dni, {NC_EXPR} AS nc,
                {PRE_RANK_EXPR.format(NC=NC_EXPR, NC_BUSQ=NC_BUSQUEDA_EXPR)}
            FROM personas p{", tsqs t" if with_tsqs else ""}
            WHERE {where_branch}
            ORDER BY pre_rank DESC, p.dni
            LIMIT :cand_limit
        )
        SELECT b.dni, b.pre_rank
        FROM base b
    """


# Multi-palabra: coincidencia estricta AND de palabras (GIN de search_vector)
BUSCAR_MULTIWORD = _candidatos_sql(
    """
    p.dni = :q
    OR p.dni LIKE :dni_prefix
    OR p.search_vector @@ t.ws_q
    """,
    with_tsqs=True,
)

# Fallback: tolerancia a typos via trigramas (en ambos órdenes de nombre)
BUSCAR_TYPO = _candidatos_sql(
    f"""
    p.dni = :q
    OR p.dni LIKE :dni_prefix
    OR (
        {NC_EXPR} % :q_lower
        AND similarity({NC_EXPR}, :q_lower) >= 0.25
    )
    OR (
        {NC_BUSQUEDA_EXPR} % :q_lower
        AND similarity({NC_BUSQUEDA_EXPR}, :q_lower) >= 0.25
    )
    """,
    with_tsqs=False,
)


RANK_PRECISO = f"""
    WITH tsqs AS (
        SELECT
            websearch_to_tsquery('simple', immutable_unaccent(:q)) AS ws_q,
            phraseto_tsquery('simple', immutable_unaccent(:q)) AS phr_q
    ),
    det AS (
        SELECT p.*, {NC_EXPR} AS nc, {NC_BUSQUEDA_EXPR} AS nc_busq
        FROM personas p
        WHERE p.dni IN :dni_list
    )
    SELECT
        det.dni, det.ap_pat, det.ap_mat, det.nombres, det.fecha_nac, det.direccion,
        {SEXO_EXPR} AS sexo,
        det.est_civil,
        det.padre, det.madre,
        det.ubigeo_nac, det.ubigeo_dir,
        det.fch_emision, det.fch_inscripcion, det.fch_caducidad,
        det.dig_ruc,
        {EDAD_COLS},
        -- Ranking ponderado ultra-preciso (A=Paterno 1.0, B=Nombres 0.4, C=Materno 0.2)
        (
            CASE WHEN det.nc = :q_lower OR det.nc_busq = :q_lower THEN 10000
                 WHEN det.nc LIKE :q_prefix OR det.nc_busq LIKE :q_prefix THEN 5000
                 ELSE 0
            END
            + CASE WHEN lower(det.ap_pat) = :q_lower THEN 3500 ELSE 0 END
            + CASE WHEN lower(det.nombres) = :q_lower THEN 3000 ELSE 0 END
            + CASE WHEN lower(det.ap_mat) = :q_lower THEN 2000 ELSE 0 END
            + CASE WHEN lower(det.ap_pat) LIKE :q_prefix THEN 800 ELSE 0 END
            + CASE WHEN lower(det.nombres) LIKE :q_prefix THEN 500 ELSE 0 END
            -- Coincidencia token por token cruzada (Paterno Materno Nombres y Nombres Paterno Materno)
            + CASE WHEN :w1 != '' AND lower(det.ap_pat) = :w1 THEN 3000 ELSE 0 END
            + CASE WHEN :w2 != '' AND lower(det.ap_mat) = :w2 THEN 2500 ELSE 0 END
            + CASE WHEN :w3 != '' AND lower(det.nombres) LIKE :w3 || '%' THEN 2000 ELSE 0 END
            + CASE WHEN :w1 != '' AND lower(det.nombres) = :w1 THEN 2000 ELSE 0 END
            + CASE WHEN :w2 != '' AND lower(det.ap_pat) = :w2 THEN 1800 ELSE 0 END
            + CASE WHEN :w3 != '' AND lower(det.ap_mat) = :w3 THEN 1500 ELSE 0 END
            + CASE WHEN :num_words_int >= 2 THEN
                ts_rank('{{0.1, 0.2, 0.4, 1.0}}', det.search_vector, t.phr_q) * 5000
              ELSE 0 END
            + ts_rank_cd('{{0.1, 0.2, 0.4, 1.0}}', det.search_vector, t.ws_q) * 500
            + GREATEST(
                COALESCE(similarity(det.nc, :q_lower), 0),
                COALESCE(similarity(det.nc_busq, :q_lower), 0)
              ) * 350
        ) AS rank_score
    FROM det, tsqs t
    ORDER BY rank_score DESC, det.dni
    LIMIT :limit
"""

RUC_POR_DNI = """
    SELECT dni, dig_ruc, ap_pat, ap_mat, nombres
    FROM personas
    WHERE dni = :dni
    LIMIT 1
"""
