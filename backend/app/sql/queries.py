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

# ═══════════════════════════════════════════════════════════════════════
# ÁRBOL GENEALÓGICO — Queries de alta precisión y velocidad indexada
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# ÁRBOL GENEALÓGICO — Queries de alta precisión con lógica biológica estricta
# ═══════════════════════════════════════════════════════════════════════

# 1. Buscar padre: GIN search_vector + regla biológica estricta de edad + correlación
BUSCAR_PADRE_RANKED = f"""
    WITH candidatos AS (
        SELECT p.*
        FROM personas p
        WHERE p.search_vector @@ to_tsquery('simple', :tsq)
        LIMIT 60
    )
    SELECT
        dni, ap_pat, ap_mat, nombres, padre, madre, fecha_nac,
        ubigeo_nac, ubigeo_dir, direccion,
        {SEXO_EXPR} AS sexo, est_civil,
        {EDAD_COLS},
        (
            -- Coincidencia exacta de nombre de pila del padre
            CASE WHEN lower(nombres) = :padre_nombre THEN 10000
                 WHEN lower(nombres) LIKE :padre_nombre || ' %' THEN 8500
                 WHEN lower(nombres) LIKE '% ' || :padre_nombre THEN 7000
                 WHEN lower(nombres) LIKE '% ' || :padre_nombre || ' %' THEN 6000
                 ELSE 0
            END
            -- Apellido paterno coincide con el del hijo (herencia directa)
            + CASE WHEN lower(ap_pat) = :hijo_ap_pat THEN 5000 ELSE 0 END
            -- Ubigeo nacimiento: distrito exacto > provincia > departamento
            + CASE WHEN :hijo_ubigeo_nac != '' AND ubigeo_nac = :hijo_ubigeo_nac THEN 4000
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(ubigeo_nac, 1, 4) = SUBSTRING(:hijo_ubigeo_nac, 1, 4) THEN 2500
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(ubigeo_nac, 1, 2) = SUBSTRING(:hijo_ubigeo_nac, 1, 2) THEN 1200
                   ELSE 0
            END
            -- Misma dirección de residencia
            + CASE WHEN :hijo_direccion != '' AND lower(direccion) = :hijo_direccion THEN 2500 ELSE 0 END
            -- Ubigeo domicilio similar
            + CASE WHEN :hijo_ubigeo_dir != '' AND ubigeo_dir = :hijo_ubigeo_dir THEN 1500
                   WHEN :hijo_ubigeo_dir != '' AND SPLIT_PART(ubigeo_dir, '-', 1) = SPLIT_PART(:hijo_ubigeo_dir, '-', 1) THEN 600
                   ELSE 0
            END
            -- Rango óptimo de edad paterna (18 a 55 años mayor)
            + CASE WHEN fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), fecha_nac)) BETWEEN 18 AND 55
                   THEN 3000
                   WHEN fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), fecha_nac)) BETWEEN 13 AND 70
                   THEN 1500
                   ELSE 0
            END
            -- Sexo masculino
            + CASE WHEN sexo::text = '1' THEN 800 ELSE 0 END
        ) AS score
    FROM candidatos
    WHERE lower(ap_pat) = :hijo_ap_pat
      -- REGLA BIOLÓGICA ESTRICTA: El padre DEBE haber nacido antes que el hijo (mínimo 13 años)
      AND (
          fecha_nac IS NULL 
          OR CAST(:hijo_fecha_nac AS date) IS NULL 
          OR (
              fecha_nac < CAST(:hijo_fecha_nac AS date) 
              AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), fecha_nac)) BETWEEN 13 AND 75
          )
      )
    ORDER BY score DESC
    LIMIT 1
"""

# 2. Buscar madre: GIN search_vector + regla biológica estricta de edad + correlación
BUSCAR_MADRE_RANKED = f"""
    WITH candidatos AS (
        SELECT p.*
        FROM personas p
        WHERE p.search_vector @@ to_tsquery('simple', :tsq)
        LIMIT 60
    )
    SELECT
        dni, ap_pat, ap_mat, nombres, padre, madre, fecha_nac,
        ubigeo_nac, ubigeo_dir, direccion,
        {SEXO_EXPR} AS sexo, est_civil,
        {EDAD_COLS},
        (
            -- Coincidencia exacta de nombre de pila de la madre
            CASE WHEN lower(nombres) = :madre_nombre THEN 10000
                 WHEN lower(nombres) LIKE :madre_nombre || ' %' THEN 8500
                 WHEN lower(nombres) LIKE '% ' || :madre_nombre THEN 7000
                 WHEN lower(nombres) LIKE '% ' || :madre_nombre || ' %' THEN 6000
                 ELSE 0
            END
            -- Apellido paterno de la madre = apellido materno del hijo
            + CASE WHEN lower(ap_pat) = :hijo_ap_mat THEN 5000 ELSE 0 END
            -- Ubigeo nacimiento: distrito exacto > provincia > departamento
            + CASE WHEN :hijo_ubigeo_nac != '' AND ubigeo_nac = :hijo_ubigeo_nac THEN 4000
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(ubigeo_nac, 1, 4) = SUBSTRING(:hijo_ubigeo_nac, 1, 4) THEN 2500
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(ubigeo_nac, 1, 2) = SUBSTRING(:hijo_ubigeo_nac, 1, 2) THEN 1200
                   ELSE 0
            END
            -- Misma dirección de residencia
            + CASE WHEN :hijo_direccion != '' AND lower(direccion) = :hijo_direccion THEN 2500 ELSE 0 END
            -- Ubigeo domicilio similar
            + CASE WHEN :hijo_ubigeo_dir != '' AND ubigeo_dir = :hijo_ubigeo_dir THEN 1500
                   WHEN :hijo_ubigeo_dir != '' AND SPLIT_PART(ubigeo_dir, '-', 1) = SPLIT_PART(:hijo_ubigeo_dir, '-', 1) THEN 600
                   ELSE 0
            END
            -- Rango óptimo de edad materna (16 a 48 años mayor)
            + CASE WHEN fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), fecha_nac)) BETWEEN 16 AND 48
                   THEN 3000
                   WHEN fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), fecha_nac)) BETWEEN 13 AND 55
                   THEN 1500
                   ELSE 0
            END
            -- Sexo femenino
            + CASE WHEN sexo::text = '2' THEN 800 ELSE 0 END
        ) AS score
    FROM candidatos
    WHERE lower(ap_pat) = :hijo_ap_mat
      -- REGLA BIOLÓGICA ESTRICTA: La madre DEBE haber nacido antes que el hijo (mínimo 13 años)
      AND (
          fecha_nac IS NULL 
          OR CAST(:hijo_fecha_nac AS date) IS NULL 
          OR (
              fecha_nac < CAST(:hijo_fecha_nac AS date) 
              AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), fecha_nac)) BETWEEN 13 AND 55
          )
      )
    ORDER BY score DESC
    LIMIT 1
"""

# 3. Buscar hermanos: cruce integral de datos compartidos + coherencia de edad
BUSCAR_HERMANOS_RANKED = f"""
    WITH candidatos AS (
        SELECT p.*
        FROM personas p
        WHERE p.search_vector @@ to_tsquery('simple', :tsq)
        LIMIT 100
    )
    SELECT
        dni, ap_pat, ap_mat, nombres, padre, madre, fecha_nac,
        ubigeo_nac, ubigeo_dir, direccion,
        {SEXO_EXPR} AS sexo, est_civil,
        {EDAD_COLS},
        (
            -- Coincidencia exacta de padre (REQUISITO FUNDAMENTAL)
            CASE WHEN :padre != '' AND lower(padre) = :padre THEN 10000
                 WHEN :padre != '' AND lower(padre) LIKE :padre || ' %' THEN 8000
                 WHEN :padre != '' AND lower(padre) LIKE '% ' || :padre THEN 7000
                 ELSE 0
            END
            -- Ambos padres coinciden exactamente (hermano de padre y madre)
            + CASE WHEN :padre != '' AND (lower(padre) = :padre OR lower(padre) LIKE :padre || ' %' OR lower(padre) LIKE '% ' || :padre)
                        AND :madre != '' AND (lower(madre) = :madre OR lower(madre) LIKE :madre || ' %' OR lower(madre) LIKE '% ' || :madre)
                   THEN 12000 ELSE 0
            END
            -- Coincidencia de madre
            + CASE WHEN :madre != '' AND lower(madre) = :madre THEN 5000
                   WHEN :madre != '' AND lower(madre) LIKE :madre || ' %' THEN 3500
                   ELSE 0
            END
            -- Comparten apellido paterno
            + CASE WHEN :hijo_ap_pat != '' AND lower(ap_pat) = :hijo_ap_pat THEN 5000 ELSE 0 END
            -- Comparten apellido materno
            + CASE WHEN :hijo_ap_mat != '' AND lower(ap_mat) = :hijo_ap_mat THEN 4000 ELSE 0 END
            -- Misma dirección de residencia exacta
            + CASE WHEN :hijo_direccion != '' AND lower(direccion) = :hijo_direccion THEN 3000 ELSE 0 END
            -- Ubigeo nacimiento: distrito > provincia > departamento
            + CASE WHEN :hijo_ubigeo_nac != '' AND ubigeo_nac = :hijo_ubigeo_nac THEN 3000
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(ubigeo_nac, 1, 4) = SUBSTRING(:hijo_ubigeo_nac, 1, 4) THEN 1800
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(ubigeo_nac, 1, 2) = SUBSTRING(:hijo_ubigeo_nac, 1, 2) THEN 800
                   ELSE 0
            END
            -- Ubigeo domicilio similar
            + CASE WHEN :hijo_ubigeo_dir != '' AND ubigeo_dir = :hijo_ubigeo_dir THEN 1500 ELSE 0 END
            -- Cercanía de edad (< 25 años)
            + CASE WHEN fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND ABS(EXTRACT(YEAR FROM age(fecha_nac, CAST(:hijo_fecha_nac AS date)))) < 25
                   THEN 2000 ELSE 0
            END
        ) AS score
    FROM candidatos
    WHERE dni != :dni_excluir
      AND (
          -- Si el padre está registrado, el hermano DEBE tener el mismo padre y mismo apellido paterno
          (:padre != '' AND lower(ap_pat) = :hijo_ap_pat AND (
              lower(padre) = :padre
              OR lower(padre) LIKE :padre || ' %'
              OR lower(padre) LIKE '% ' || :padre
          ))
          -- O si no hay padre registrado, coincidir en madre y apellido materno
          OR (:padre = '' AND :madre != '' AND lower(ap_mat) = :hijo_ap_mat AND (
              lower(madre) = :madre
              OR lower(madre) LIKE :madre || ' %'
              OR lower(madre) LIKE '% ' || :madre
          ))
      )
      -- REGLA BIOLÓGICA: La diferencia de edad entre hermanos no debe exceder el periodo reproductivo
      AND (
          fecha_nac IS NULL 
          OR CAST(:hijo_fecha_nac AS date) IS NULL 
          OR ABS(EXTRACT(YEAR FROM age(fecha_nac, CAST(:hijo_fecha_nac AS date)))) <= 35
      )
    ORDER BY score DESC
    LIMIT 15
"""

# 4. Buscar hijos: GIN search_vector + regla biológica estricta (hijo NUNCA mayor que progenitor)
BUSCAR_HIJOS_RANKED = f"""
    WITH candidatos AS (
        SELECT p.*
        FROM personas p
        WHERE p.search_vector @@ to_tsquery('simple', :tsq)
        LIMIT 100
    )
    SELECT
        dni, ap_pat, ap_mat, nombres, padre, madre, fecha_nac,
        ubigeo_nac, ubigeo_dir, direccion,
        {SEXO_EXPR} AS sexo, est_civil,
        {EDAD_COLS},
        (
            -- El nombre del progenitor coincide exactamente en el campo padre o madre
            CASE WHEN :es_padre AND lower(padre) = :progenitor_nombre THEN 8000
                 WHEN NOT :es_padre AND lower(madre) = :progenitor_nombre THEN 8000
                 WHEN :es_padre AND lower(padre) LIKE :progenitor_nombre || ' %' THEN 6000
                 WHEN NOT :es_padre AND lower(madre) LIKE :progenitor_nombre || ' %' THEN 6000
                 ELSE 0
            END
            -- Cónyuge coincide si se conoce
            + CASE WHEN :conyuge_nombre != '' AND (:es_padre AND lower(madre) = :conyuge_nombre OR NOT :es_padre AND lower(padre) = :conyuge_nombre) THEN 5000 ELSE 0 END
            -- Herencia de apellido paterno / materno
            + CASE WHEN :es_padre AND lower(ap_pat) = :progenitor_ap_pat THEN 4000
                   WHEN NOT :es_padre AND lower(ap_mat) = :progenitor_ap_pat THEN 4000
                   ELSE 0
            END
            -- Misma dirección de residencia
            + CASE WHEN :progenitor_direccion != '' AND lower(direccion) = :progenitor_direccion THEN 2500 ELSE 0 END
            -- Ubigeo nacimiento
            + CASE WHEN :progenitor_ubigeo != '' AND ubigeo_nac = :progenitor_ubigeo THEN 3000
                   WHEN :progenitor_ubigeo != '' AND SUBSTRING(ubigeo_nac, 1, 4) = SUBSTRING(:progenitor_ubigeo, 1, 4) THEN 1500
                   WHEN :progenitor_ubigeo != '' AND SUBSTRING(ubigeo_nac, 1, 2) = SUBSTRING(:progenitor_ubigeo, 1, 2) THEN 600
                   ELSE 0
            END
            -- Edad coherente (el progenitor tenía entre 15 y 55 años cuando nació el hijo)
            + CASE WHEN fecha_nac IS NOT NULL AND CAST(:progenitor_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(fecha_nac, CAST(:progenitor_fecha_nac AS date))) BETWEEN 15 AND 55
                   THEN 3000 ELSE 0
            END
        ) AS score
    FROM candidatos
    WHERE (
        (:es_padre AND (lower(padre) LIKE '%' || :progenitor_nombre || '%' OR lower(ap_pat) = :progenitor_ap_pat))
        OR (NOT :es_padre AND (lower(madre) LIKE '%' || :progenitor_nombre || '%' OR lower(ap_mat) = :progenitor_ap_pat))
    )
      -- REGLA BIOLÓGICA ESTRICTA: El hijo NUNCA puede ser mayor o de igual edad que su padre/madre
      AND (
          fecha_nac IS NULL 
          OR CAST(:progenitor_fecha_nac AS date) IS NULL 
          OR (
              fecha_nac > CAST(:progenitor_fecha_nac AS date)
              AND EXTRACT(YEAR FROM age(fecha_nac, CAST(:progenitor_fecha_nac AS date))) BETWEEN 13 AND 70
          )
      )
    ORDER BY score DESC
    LIMIT 15
"""

RUC_POR_DNI = """
    SELECT dni, dig_ruc, ap_pat, ap_mat, nombres
    FROM personas
    WHERE dni = :dni
    LIMIT 1
"""
