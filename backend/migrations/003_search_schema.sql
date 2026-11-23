-- Migración de esquema de búsqueda para bases existentes.
--
-- `docker/initdb.sql` crea estas columnas e índices en instalaciones nuevas,
-- pero las migraciones 001 y 002 no las añadían a una base ya creada. Sin
-- `search_vector`, todas las consultas FTS devuelven vacío (y antes de la
-- corrección del backend ni siquiera se distinguía de "sin resultados").
--
-- EJECUTAR FUERA DE UNA TRANSACCIÓN (CREATE INDEX CONCURRENTLY):
--   psql "${DATABASE_URL/postgresql+psycopg2/postgresql}" \
--     -v ON_ERROR_STOP=1 -f backend/migrations/003_search_schema.sql
--
-- En una tabla de ~37 M filas añadir columnas generadas reescribe la tabla;
-- planifica ventanas de mantenimiento y espacio en disco.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text AS $$
    SELECT public.unaccent(public.unaccent($1))
$$ LANGUAGE sql IMMUTABLE STRICT;

CREATE OR REPLACE FUNCTION build_nombre_completo(nombres text, ap_pat text, ap_mat text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(
        ' ',
        trim(coalesce(nombres, '')),
        trim(coalesce(ap_pat, '')),
        trim(coalesce(ap_mat, ''))
    ))))
$$ LANGUAGE sql IMMUTABLE STRICT;

CREATE OR REPLACE FUNCTION build_nombre_busqueda(ap_pat text, ap_mat text, nombres text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(
        ' ',
        trim(coalesce(ap_pat, '')),
        trim(coalesce(ap_mat, '')),
        trim(coalesce(nombres, ''))
    ))))
$$ LANGUAGE sql IMMUTABLE STRICT;

ALTER TABLE personas
    ADD COLUMN IF NOT EXISTS nombre_completo TEXT GENERATED ALWAYS AS (
        build_nombre_completo(nombres, ap_pat, ap_mat)
    ) STORED,
    ADD COLUMN IF NOT EXISTS nombre_busqueda TEXT GENERATED ALWAYS AS (
        build_nombre_busqueda(ap_pat, ap_mat, nombres)
    ) STORED,
    ADD COLUMN IF NOT EXISTS ap_pat_soundex TEXT GENERATED ALWAYS AS (
        soundex(immutable_unaccent(coalesce(ap_pat, '')))
    ) STORED,
    ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(nombres, ''))), 'A') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(ap_pat, ''))), 'A') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(ap_mat, ''))), 'A') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(dni, '')::text)), 'B')
    ) STORED;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_search_vector
    ON personas USING gin (search_vector);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_nombre_trgm
    ON personas USING gin (build_nombre_completo(nombres, ap_pat, ap_mat) gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_nombre_busqueda_trgm
    ON personas USING gin (build_nombre_busqueda(ap_pat, ap_mat, nombres) gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_dni_like
    ON personas (dni text_pattern_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_ap_pat_soundex
    ON personas (ap_pat_soundex);

ANALYZE personas;
