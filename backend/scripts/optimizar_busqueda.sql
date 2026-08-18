-- Índices y optimizaciones de alto rendimiento para búsqueda por nombre
-- Ejecutar como superusuario:
--   cat scripts/optimizar_busqueda.sql | sudo -u postgres psql -d buscador_personas

SET maintenance_work_mem = '2GB';

-- 1) Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- 2) Funciones inmutables auxiliares
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text AS $$
    SELECT public.unaccent(public.unaccent($1))
$$ LANGUAGE sql IMMUTABLE STRICT;

CREATE OR REPLACE FUNCTION build_nombre_completo(nombres text, ap_pat text, ap_mat text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(' ', trim(coalesce(nombres, '')), trim(coalesce(ap_pat, '')), trim(coalesce(ap_mat, ''))))))
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION build_nombre_busqueda(ap_pat text, ap_mat text, nombres text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(' ', trim(coalesce(ap_pat, '')), trim(coalesce(ap_mat, '')), trim(coalesce(nombres, ''))))))
$$ LANGUAGE sql IMMUTABLE;

-- 3) Columnas generadas (si no existen)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='personas' AND column_name='nombre_busqueda') THEN
        ALTER TABLE personas ADD COLUMN nombre_busqueda TEXT GENERATED ALWAYS AS (
            lower(immutable_unaccent(trim(coalesce(ap_pat, '')) || ' ' || trim(coalesce(ap_mat, '')) || ' ' || trim(coalesce(nombres, ''))))
        ) STORED;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='personas' AND column_name='ap_pat_soundex') THEN
        ALTER TABLE personas ADD COLUMN ap_pat_soundex TEXT GENERATED ALWAYS AS (
            soundex(immutable_unaccent(coalesce(ap_pat, '')))
        ) STORED;
    END IF;
END $$;

-- 4) Trigramas de nombres completos (ambos órdenes: formal y natural)
CREATE INDEX IF NOT EXISTS idx_personas_nombre_trgm
    ON personas USING gin (build_nombre_completo(nombres, ap_pat, ap_mat) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_personas_nombre_busqueda_trgm
    ON personas USING gin (build_nombre_busqueda(ap_pat, ap_mat, nombres) gin_trgm_ops);

-- 5) Prefijo de DNI en búsqueda por nombre
CREATE INDEX IF NOT EXISTS idx_personas_dni_like
    ON personas (dni text_pattern_ops);

-- 6) Índice fonético soundex
CREATE INDEX IF NOT EXISTS idx_personas_ap_pat_soundex
    ON personas (ap_pat_soundex);

-- 7) Buckets por componente con Index-Only Scan (INCLUDE)
CREATE INDEX IF NOT EXISTS idx_personas_ap_pat_lower
    ON personas (lower(ap_pat) text_pattern_ops) INCLUDE (dni, nombres, ap_mat);

CREATE INDEX IF NOT EXISTS idx_personas_nombres_lower
    ON personas (lower(nombres) text_pattern_ops) INCLUDE (dni, ap_pat, ap_mat);

DROP INDEX IF EXISTS idx_personas_ap_mat_lower;
CREATE INDEX IF NOT EXISTS idx_personas_ap_mat_lower
    ON personas (lower(ap_mat) text_pattern_ops) INCLUDE (dni, nombres, ap_pat);

-- 8) Actualizar estadísticas del optimizador de consultas
VACUUM ANALYZE personas;
