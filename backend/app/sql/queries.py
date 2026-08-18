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

MAX_CANDIDATOS = 100   # Candidatos óptimos para ranking ultra-preciso en < 30ms

# Selección ultrarrápida por índice GIN (search_vector)
CANDIDATOS_TSQUERY = """
    SELECT p.dni
    FROM personas p
    WHERE p.search_vector @@ to_tsquery('simple', :tsq)
    LIMIT :cand_limit
"""

# Selección directa de DNI exacto o prefijo
CANDIDATOS_DNI = """
    SELECT p.dni
    FROM personas p
    WHERE p.dni = :q OR p.dni LIKE :dni_prefix
    LIMIT :cand_limit
"""

# Re-ranking de máxima precisión sobre el conjunto de candidatos
RANK_PRECISO = f"""
    WITH tsqs AS (
        SELECT
            websearch_to_tsquery('simple', immutable_unaccent(:q)) AS ws_q,
            phraseto_tsquery('simple', immutable_unaccent(:q)) AS phr_q
    ),
    det AS (
        SELECT p.*,
            {NC_EXPR} AS nc,
            {NC_BUSQUEDA_EXPR} AS nc_busq
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
        -- Algoritmo de ponderación jerárquica para máxima precisión
        (
            -- Coincidencia exacta de nombre completo (en ambos órdenes peruanos)
            CASE WHEN det.nc = :q_lower OR det.nc_busq = :q_lower THEN 10000
                 WHEN det.nc LIKE :q_prefix OR det.nc_busq LIKE :q_prefix THEN 5000
                 ELSE 0
            END
            -- Coincidencia exacta por componente
            + CASE WHEN lower(det.ap_pat) = :q_lower THEN 4500 ELSE 0 END
            + CASE WHEN lower(det.nombres) = :q_lower THEN 4000 ELSE 0 END
            + CASE WHEN lower(det.ap_mat) = :q_lower THEN 3000 ELSE 0 END
            + CASE WHEN lower(det.ap_pat) LIKE :q_prefix THEN 1000 ELSE 0 END
            + CASE WHEN lower(det.nombres) LIKE :q_prefix THEN 800 ELSE 0 END
            -- Alineación estructural de apellidos y nombres (Paterno + Materno / Nombres + Paterno)
            + CASE WHEN :w1 != '' AND lower(det.ap_pat) = :w1 AND :w2 != '' AND lower(det.ap_mat) = :w2 THEN 6000 ELSE 0 END
            + CASE WHEN :w1 != '' AND lower(det.nombres) LIKE :w1 || '%' AND :w2 != '' AND lower(det.ap_pat) = :w2 THEN 5500 ELSE 0 END
            + CASE WHEN :w1 != '' AND lower(det.ap_pat) = :w1 AND :w2 != '' AND lower(det.nombres) LIKE :w2 || '%' THEN 5500 ELSE 0 END
            + CASE WHEN :w1 != '' AND lower(det.ap_pat) = :w1 AND :w2 != '' AND lower(det.ap_mat) = :w2 AND :w3 != '' AND lower(det.nombres) LIKE :w3 || '%' THEN 7500 ELSE 0 END
            + CASE WHEN :w1 != '' AND lower(det.nombres) LIKE :w1 || '%' AND :w2 != '' AND lower(det.ap_pat) = :w2 AND :w3 != '' AND lower(det.ap_mat) = :w3 THEN 7500 ELSE 0 END
            -- Puntos individuales por coincidencia de tokens
            + CASE WHEN :w1 != '' AND lower(det.ap_pat) = :w1 THEN 2500 ELSE 0 END
            + CASE WHEN :w1 != '' AND lower(det.nombres) LIKE :w1 || '%' THEN 2000 ELSE 0 END
            + CASE WHEN :w2 != '' AND lower(det.ap_mat) = :w2 THEN 2000 ELSE 0 END
            + CASE WHEN :w2 != '' AND lower(det.ap_pat) = :w2 THEN 1800 ELSE 0 END
            + CASE WHEN :w2 != '' AND lower(det.nombres) LIKE :w2 || '%' THEN 1500 ELSE 0 END
            + CASE WHEN :w3 != '' AND lower(det.ap_mat) = :w3 THEN 1500 ELSE 0 END
            + CASE WHEN :w3 != '' AND lower(det.nombres) LIKE :w3 || '%' THEN 1200 ELSE 0 END
            -- Ranking de frase exacta y cobertura textual
            + CASE WHEN :num_words_int >= 2 THEN
                ts_rank('{{0.1, 0.2, 0.4, 1.0}}', det.search_vector, t.phr_q) * 5000
              ELSE 0 END
            + ts_rank_cd('{{0.1, 0.2, 0.4, 1.0}}', det.search_vector, t.ws_q) * 600
            -- Similitud trigramétrica sobre el subconjunto de candidatos
            + GREATEST(
                COALESCE(similarity(det.nc, :q_lower), 0),
                COALESCE(similarity(det.nc_busq, :q_lower), 0)
              ) * 400
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
