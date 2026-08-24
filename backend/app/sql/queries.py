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
    SELECT
        p.dni, p.ap_pat, p.ap_mat, p.nombres, p.padre, p.madre, p.fecha_nac,
        p.ubigeo_nac, p.ubigeo_dir, p.direccion,
        {SEXO_EXPR} AS sexo, p.est_civil,
        {EDAD_COLS},
        (
            -- Coincidencia exacta de nombre de pila del padre
            CASE WHEN lower(p.nombres) = :padre_nombre THEN 10000
                 WHEN lower(p.nombres) LIKE :padre_nombre || ' %' THEN 8500
                 WHEN lower(p.nombres) LIKE '% ' || :padre_nombre THEN 7000
                 WHEN lower(p.nombres) LIKE '% ' || :padre_nombre || ' %' THEN 6000
                 ELSE 0
            END
            -- Apellido paterno coincide con el del hijo (herencia directa)
            + CASE WHEN lower(p.ap_pat) = :hijo_ap_pat THEN 5000 ELSE 0 END
            -- Ubigeo nacimiento: distrito exacto > provincia > departamento
            + CASE WHEN :hijo_ubigeo_nac != '' AND p.ubigeo_nac = :hijo_ubigeo_nac THEN 4000
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 4) = SUBSTRING(:hijo_ubigeo_nac, 1, 4) THEN 2500
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 2) = SUBSTRING(:hijo_ubigeo_nac, 1, 2) THEN 1200
                   ELSE 0
            END
            -- Misma dirección de residencia
            + CASE WHEN :hijo_direccion != '' AND lower(p.direccion) = :hijo_direccion THEN 2500 ELSE 0 END
            -- Ubigeo domicilio similar
            + CASE WHEN :hijo_ubigeo_dir != '' AND p.ubigeo_dir = :hijo_ubigeo_dir THEN 1500
                   WHEN :hijo_ubigeo_dir != '' AND SPLIT_PART(p.ubigeo_dir, '-', 1) = SPLIT_PART(:hijo_ubigeo_dir, '-', 1) THEN 600
                   ELSE 0
            END
            -- Rango óptimo de edad paterna (18 a 55 años mayor)
            + CASE WHEN p.fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), p.fecha_nac)) BETWEEN 18 AND 55
                   THEN 3000
                   WHEN p.fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), p.fecha_nac)) BETWEEN 13 AND 70
                   THEN 1500
                   ELSE 0
            END
            -- Sexo masculino
            + CASE WHEN p.sexo::text = '1' THEN 800 ELSE 0 END
        ) AS score
    FROM personas p
    WHERE p.search_vector @@ to_tsquery('simple', :tsq)
      AND lower(p.ap_pat) = :hijo_ap_pat
      -- REGLA BIOLÓGICA ESTRICTA: El padre DEBE haber nacido antes que el hijo (mínimo 13 años)
      AND (
          p.fecha_nac IS NULL 
          OR CAST(:hijo_fecha_nac AS date) IS NULL 
          OR (
              p.fecha_nac < CAST(:hijo_fecha_nac AS date) 
              AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), p.fecha_nac)) BETWEEN 13 AND 75
          )
      )
    ORDER BY score DESC
    LIMIT 1
"""

# 2. Buscar madre: GIN search_vector + regla biológica estricta de edad + correlación
BUSCAR_MADRE_RANKED = f"""
    SELECT
        p.dni, p.ap_pat, p.ap_mat, p.nombres, p.padre, p.madre, p.fecha_nac,
        p.ubigeo_nac, p.ubigeo_dir, p.direccion,
        {SEXO_EXPR} AS sexo, p.est_civil,
        {EDAD_COLS},
        (
            -- Coincidencia exacta de nombre de pila de la madre
            CASE WHEN lower(p.nombres) = :madre_nombre THEN 10000
                 WHEN lower(p.nombres) LIKE :madre_nombre || ' %' THEN 8500
                 WHEN lower(p.nombres) LIKE '% ' || :madre_nombre THEN 7000
                 WHEN lower(p.nombres) LIKE '% ' || :madre_nombre || ' %' THEN 6000
                 ELSE 0
            END
            -- Apellido paterno de la madre = apellido materno del hijo
            + CASE WHEN lower(p.ap_pat) = :hijo_ap_mat THEN 5000 ELSE 0 END
            -- Ubigeo nacimiento: distrito exacto > provincia > departamento
            + CASE WHEN :hijo_ubigeo_nac != '' AND p.ubigeo_nac = :hijo_ubigeo_nac THEN 4000
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 4) = SUBSTRING(:hijo_ubigeo_nac, 1, 4) THEN 2500
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 2) = SUBSTRING(:hijo_ubigeo_nac, 1, 2) THEN 1200
                   ELSE 0
            END
            -- Misma dirección de residencia
            + CASE WHEN :hijo_direccion != '' AND lower(p.direccion) = :hijo_direccion THEN 2500 ELSE 0 END
            -- Ubigeo domicilio similar
            + CASE WHEN :hijo_ubigeo_dir != '' AND p.ubigeo_dir = :hijo_ubigeo_dir THEN 1500
                   WHEN :hijo_ubigeo_dir != '' AND SPLIT_PART(p.ubigeo_dir, '-', 1) = SPLIT_PART(:hijo_ubigeo_dir, '-', 1) THEN 600
                   ELSE 0
            END
            -- Rango óptimo de edad materna (16 a 48 años mayor)
            + CASE WHEN p.fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), p.fecha_nac)) BETWEEN 16 AND 48
                   THEN 3000
                   WHEN p.fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), p.fecha_nac)) BETWEEN 13 AND 55
                   THEN 1500
                   ELSE 0
            END
            -- Sexo femenino
            + CASE WHEN p.sexo::text = '2' THEN 800 ELSE 0 END
        ) AS score
    FROM personas p
    WHERE p.search_vector @@ to_tsquery('simple', :tsq)
      AND lower(p.ap_pat) = :hijo_ap_mat
      -- REGLA BIOLÓGICA ESTRICTA: La madre DEBE haber nacido antes que el hijo (mínimo 13 años)
      AND (
          p.fecha_nac IS NULL 
          OR CAST(:hijo_fecha_nac AS date) IS NULL 
          OR (
              p.fecha_nac < CAST(:hijo_fecha_nac AS date) 
              AND EXTRACT(YEAR FROM age(CAST(:hijo_fecha_nac AS date), p.fecha_nac)) BETWEEN 13 AND 55
          )
      )
    ORDER BY score DESC
    LIMIT 1
"""

# 3. Buscar hermanos: cruce integral de datos compartidos (padre, madre, ubigeo, dirección) + coherencia de edad
BUSCAR_HERMANOS_RANKED = f"""
    SELECT
        p.dni, p.ap_pat, p.ap_mat, p.nombres, p.padre, p.madre, p.fecha_nac,
        p.ubigeo_nac, p.ubigeo_dir, p.direccion,
        {SEXO_EXPR} AS sexo, p.est_civil,
        {EDAD_COLS},
        (
            -- Mismo Padre Y Misma Madre (HERMANO COMPLETO DE SANGRE - MÁXIMA PONDERACIÓN)
            CASE WHEN :padre != '' AND (lower(p.padre) = :padre OR lower(p.padre) LIKE :padre || ' %' OR lower(p.padre) LIKE '% ' || :padre)
                      AND :madre != '' AND (lower(p.madre) = :madre OR lower(p.madre) LIKE :madre || ' %' OR lower(p.madre) LIKE '% ' || :madre)
                 THEN 25000
                 -- Solo coincide padre
                 WHEN :padre != '' AND (lower(p.padre) = :padre OR lower(p.padre) LIKE :padre || ' %' OR lower(p.padre) LIKE '% ' || :padre)
                 THEN 10000
                 -- Solo coincide madre
                 WHEN :madre != '' AND (lower(p.madre) = :madre OR lower(p.madre) LIKE :madre || ' %' OR lower(p.madre) LIKE '% ' || :madre)
                 THEN 8000
                 ELSE 0
            END
            -- Comparten apellido paterno (herencia del padre)
            + CASE WHEN :hijo_ap_pat != '' AND lower(p.ap_pat) = :hijo_ap_pat THEN 5000 ELSE 0 END
            -- Comparten apellido materno (herencia de la madre)
            + CASE WHEN :hijo_ap_mat != '' AND lower(p.ap_mat) = :hijo_ap_mat THEN 4000 ELSE 0 END
            -- Misma dirección física exacta de residencia
            + CASE WHEN :hijo_direccion != '' AND lower(p.direccion) = :hijo_direccion THEN 5000 ELSE 0 END
            -- Ubigeo nacimiento: distrito exacto > provincia > departamento
            + CASE WHEN :hijo_ubigeo_nac != '' AND p.ubigeo_nac = :hijo_ubigeo_nac THEN 5000
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 4) = SUBSTRING(:hijo_ubigeo_nac, 1, 4) THEN 3000
                   WHEN :hijo_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 2) = SUBSTRING(:hijo_ubigeo_nac, 1, 2) THEN 1200
                   ELSE 0
            END
            -- Ubigeo domicilio: distrito exacto > departamento
            + CASE WHEN :hijo_ubigeo_dir != '' AND p.ubigeo_dir = :hijo_ubigeo_dir THEN 3000
                   WHEN :hijo_ubigeo_dir != '' AND SPLIT_PART(p.ubigeo_dir, '-', 1) = SPLIT_PART(:hijo_ubigeo_dir, '-', 1) THEN 1200
                   ELSE 0
            END
            -- Cercanía de edad (< 25 años)
            + CASE WHEN p.fecha_nac IS NOT NULL AND CAST(:hijo_fecha_nac AS date) IS NOT NULL
                        AND ABS(EXTRACT(YEAR FROM age(p.fecha_nac, CAST(:hijo_fecha_nac AS date)))) < 25
                   THEN 2000 ELSE 0
            END
        ) AS score
    FROM personas p
    WHERE p.search_vector @@ to_tsquery('simple', :tsq)
      AND p.dni != :dni_excluir
      AND (
          -- CASO 1: Si la persona tiene PADRE y MADRE registrados -> El hermano DEBE tener AMBOS padres y AMBOS apellidos coincidentes
          (:padre != '' AND :madre != '' AND lower(p.ap_pat) = :hijo_ap_pat AND lower(p.ap_mat) = :hijo_ap_mat AND (
              (lower(p.padre) = :padre OR lower(p.padre) LIKE :padre || ' %' OR lower(p.padre) LIKE '% ' || :padre)
              AND (lower(p.madre) = :madre OR lower(p.madre) LIKE :madre || ' %' OR lower(p.madre) LIKE '% ' || :madre)
          ))
          -- CASO 2: Si solo tiene padre registrado -> Coincidir en padre y apellido paterno
          OR (:padre != '' AND :madre = '' AND lower(p.ap_pat) = :hijo_ap_pat AND (
              lower(p.padre) = :padre
              OR lower(p.padre) LIKE :padre || ' %'
              OR lower(p.padre) LIKE '% ' || :padre
          ))
          -- CASO 3: Si solo tiene madre registrada -> Coincidir en madre y apellido materno
          OR (:padre = '' AND :madre != '' AND lower(p.ap_mat) = :hijo_ap_mat AND (
              lower(p.madre) = :madre
              OR lower(p.madre) LIKE :madre || ' %'
              OR lower(p.madre) LIKE '% ' || :madre
          ))
      )
      -- REGLA BIOLÓGICA: La diferencia de edad entre hermanos no debe exceder el periodo reproductivo (<= 32 años)
      AND (
          p.fecha_nac IS NULL 
          OR CAST(:hijo_fecha_nac AS date) IS NULL 
          OR ABS(EXTRACT(YEAR FROM age(p.fecha_nac, CAST(:hijo_fecha_nac AS date)))) <= 32
      )
    ORDER BY score DESC
    LIMIT 15
"""

# 4. Buscar hijos: cruce integral de datos compartidos (nombre progenitor, apellidos, ubigeos, dirección, edad)
BUSCAR_HIJOS_RANKED = f"""
    SELECT
        p.dni, p.ap_pat, p.ap_mat, p.nombres, p.padre, p.madre, p.fecha_nac,
        p.ubigeo_nac, p.ubigeo_dir, p.direccion,
        {SEXO_EXPR} AS sexo, p.est_civil,
        {EDAD_COLS},
        (
            -- 1. Coincidencia de nombre del progenitor en campo padre o madre
            CASE WHEN :es_padre AND :progenitor_nombre_completo != '' AND lower(p.padre) = :progenitor_nombre_completo THEN 15000
                 WHEN NOT :es_padre AND :progenitor_nombre_completo != '' AND lower(p.madre) = :progenitor_nombre_completo THEN 15000
                 WHEN :es_padre AND lower(p.padre) = :progenitor_nombre THEN 10000
                 WHEN NOT :es_padre AND lower(p.madre) = :progenitor_nombre THEN 10000
                 WHEN :es_padre AND lower(p.padre) LIKE :progenitor_nombre || ' %' THEN 8000
                 WHEN NOT :es_padre AND lower(p.madre) LIKE :progenitor_nombre || ' %' THEN 8000
                 WHEN :es_padre AND lower(p.padre) LIKE '% ' || :progenitor_nombre THEN 6000
                 WHEN NOT :es_padre AND lower(p.madre) LIKE '% ' || :progenitor_nombre THEN 6000
                 WHEN :es_padre AND lower(p.padre) LIKE '% ' || :progenitor_nombre || ' %' THEN 5000
                 WHEN NOT :es_padre AND lower(p.madre) LIKE '% ' || :progenitor_nombre || ' %' THEN 5000
                 ELSE 0
            END
            -- 2. Herencia de apellidos compartidos
            + CASE WHEN :es_padre AND lower(p.ap_pat) = :progenitor_ap_pat THEN 6000
                   WHEN NOT :es_padre AND lower(p.ap_mat) = :progenitor_ap_pat THEN 6000
                   ELSE 0
            END
            + CASE WHEN :progenitor_ap_mat != '' AND (
                       (:es_padre AND lower(p.ap_mat) = :progenitor_ap_mat)
                       OR (NOT :es_padre AND lower(p.ap_mat) = :progenitor_ap_mat)
                   ) THEN 2500 ELSE 0
            END
            -- 3. Ubigeo de nacimiento compartido (distrito exacto > provincia > departamento)
            + CASE WHEN :progenitor_ubigeo_nac != '' AND p.ubigeo_nac = :progenitor_ubigeo_nac THEN 5000
                   WHEN :progenitor_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 4) = SUBSTRING(:progenitor_ubigeo_nac, 1, 4) THEN 3000
                   WHEN :progenitor_ubigeo_nac != '' AND SUBSTRING(p.ubigeo_nac, 1, 2) = SUBSTRING(:progenitor_ubigeo_nac, 1, 2) THEN 1200
                   ELSE 0
            END
            -- 4. Ubigeo de domicilio compartido (distrito exacto > departamento)
            + CASE WHEN :progenitor_ubigeo_dir != '' AND p.ubigeo_dir = :progenitor_ubigeo_dir THEN 4000
                   WHEN :progenitor_ubigeo_dir != '' AND SPLIT_PART(p.ubigeo_dir, '-', 1) = SPLIT_PART(:progenitor_ubigeo_dir, '-', 1) THEN 1500
                   ELSE 0
            END
            -- 5. Cruce de geolocalización (nacimiento del hijo coincide con domicilio del padre o viceversa)
            + CASE WHEN :progenitor_ubigeo_dir != '' AND p.ubigeo_nac != '' AND :progenitor_ubigeo_nac != ''
                        AND p.ubigeo_nac = :progenitor_ubigeo_dir THEN 2500
                   WHEN :progenitor_ubigeo_nac != '' AND p.ubigeo_dir != ''
                        AND p.ubigeo_dir = :progenitor_ubigeo_nac THEN 2000
                   ELSE 0
            END
            -- 6. Misma dirección física exacta o coincidencia de localidad/comunidad/calle
            + CASE WHEN :progenitor_direccion != '' AND lower(p.direccion) = :progenitor_direccion THEN 6000
                   WHEN :progenitor_direccion != '' AND (
                       lower(p.direccion) LIKE '%' || :progenitor_direccion || '%'
                       OR :progenitor_direccion LIKE '%' || lower(p.direccion) || '%'
                   ) THEN 4000
                   ELSE 0
            END
            -- 7. Coherencia biológica y rango óptimo de edad reproductiva
            + CASE WHEN p.fecha_nac IS NOT NULL AND CAST(:progenitor_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(p.fecha_nac, CAST(:progenitor_fecha_nac AS date))) BETWEEN 18 AND 42
                   THEN 4000
                   WHEN p.fecha_nac IS NOT NULL AND CAST(:progenitor_fecha_nac AS date) IS NOT NULL
                        AND EXTRACT(YEAR FROM age(p.fecha_nac, CAST(:progenitor_fecha_nac AS date))) BETWEEN 14 AND 55
                   THEN 2000
                   ELSE 0
            END
        ) AS score
    FROM personas p
    WHERE p.search_vector @@ to_tsquery('simple', :tsq)
      AND p.dni != :progenitor_dni
      -- REQUISITO 1: El campo padre/madre DEBE contener el nombre del progenitor
      AND (
          (:es_padre AND p.padre IS NOT NULL AND p.padre != '' AND (
              lower(p.padre) = :progenitor_nombre
              OR lower(p.padre) = :progenitor_nombre_completo
              OR lower(p.padre) LIKE :progenitor_nombre || ' %'
              OR lower(p.padre) LIKE '% ' || :progenitor_nombre
              OR lower(p.padre) LIKE '% ' || :progenitor_nombre || ' %'
          ))
          OR (NOT :es_padre AND p.madre IS NOT NULL AND p.madre != '' AND (
              lower(p.madre) = :progenitor_nombre
              OR lower(p.madre) = :progenitor_nombre_completo
              OR lower(p.madre) LIKE :progenitor_nombre || ' %'
              OR lower(p.madre) LIKE '% ' || :progenitor_nombre
              OR lower(p.madre) LIKE '% ' || :progenitor_nombre || ' %'
          ))
      )
      -- REQUISITO 2: Herencia obligatoria del apellido
      AND (
          (:es_padre AND lower(p.ap_pat) = :progenitor_ap_pat)
          OR (NOT :es_padre AND lower(p.ap_mat) = :progenitor_ap_pat)
      )
      -- REGLA BIOLÓGICA ESTRICTA: El hijo NUNCA puede ser mayor o de igual edad que su progenitor
      AND p.fecha_nac IS NOT NULL
      AND CAST(:progenitor_fecha_nac AS date) IS NOT NULL
      AND p.fecha_nac > CAST(:progenitor_fecha_nac AS date)
      AND EXTRACT(YEAR FROM age(p.fecha_nac, CAST(:progenitor_fecha_nac AS date))) BETWEEN 13 AND 70
    ORDER BY score DESC
    LIMIT 20
"""

RUC_POR_DNI = """
    SELECT dni, dig_ruc, ap_pat, ap_mat, nombres
    FROM personas
    WHERE dni = :dni
    LIMIT 1
"""
