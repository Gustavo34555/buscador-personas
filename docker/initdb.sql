-- Inicialización de PostgreSQL para el Buscador de Personas.
-- Se ejecuta automáticamente al levantar un volumen nuevo de Docker.
-- Para bases existentes usar backend/migrations/*.sql.

-- 1. Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- 2. Función unaccent inmutable para índices y consultas rápidas
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text AS $$
    SELECT public.unaccent(public.unaccent($1))
$$ LANGUAGE sql IMMUTABLE STRICT;

-- 3. Funciones auxiliares de normalización
CREATE OR REPLACE FUNCTION build_nombre_completo(nombres text, ap_pat text, ap_mat text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(
        ' ',
        trim(coalesce(nombres, '')),
        trim(coalesce(ap_pat, '')),
        trim(coalesce(ap_mat, ''))
    ))))
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION build_nombre_busqueda(ap_pat text, ap_mat text, nombres text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(
        ' ',
        trim(coalesce(ap_pat, '')),
        trim(coalesce(ap_mat, '')),
        trim(coalesce(nombres, ''))
    ))))
$$ LANGUAGE sql IMMUTABLE;

-- 4. Tabla principal de personas
CREATE TABLE IF NOT EXISTS personas (
    id BIGSERIAL PRIMARY KEY,
    dni VARCHAR(8) NOT NULL UNIQUE,
    ap_pat TEXT,
    ap_mat TEXT,
    nombres TEXT,
    fecha_nac DATE,
    fch_inscripcion DATE,
    fch_emision DATE,
    fch_caducidad DATE,
    ubigeo_nac TEXT,
    ubigeo_dir TEXT,
    ubigeo_codigo VARCHAR(10),
    direccion TEXT,
    sexo TEXT,
    est_civil TEXT,
    dig_ruc TEXT,
    padre TEXT,
    madre TEXT,
    nombre_completo TEXT GENERATED ALWAYS AS (
        build_nombre_completo(nombres, ap_pat, ap_mat)
    ) STORED,
    nombre_busqueda TEXT GENERATED ALWAYS AS (
        build_nombre_busqueda(ap_pat, ap_mat, nombres)
    ) STORED,
    ap_pat_soundex TEXT GENERATED ALWAYS AS (
        soundex(immutable_unaccent(coalesce(ap_pat, '')))
    ) STORED,
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(nombres, ''))), 'A') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(ap_pat, ''))), 'A') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(ap_mat, ''))), 'A') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(dni, '')::text)), 'B')
    ) STORED
);

-- 5. Usuarios y auditoría
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rol VARCHAR(20) NOT NULL DEFAULT 'user',
    consultas_max INTEGER NOT NULL DEFAULT 100,
    consultas_usadas INTEGER NOT NULL DEFAULT 0,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    token_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT usuarios_rol_check CHECK (rol IN ('admin', 'user')),
    CONSTRAINT usuarios_consultas_check CHECK (consultas_max >= 0 AND consultas_usadas >= 0)
);

CREATE TABLE IF NOT EXISTS auditoria_consultas (
    id SERIAL PRIMARY KEY,
    ip VARCHAR(45) NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    query VARCHAR(500) NOT NULL,
    fecha TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Índices de búsqueda
CREATE INDEX IF NOT EXISTS idx_personas_search_vector
    ON personas USING gin (search_vector);

CREATE INDEX IF NOT EXISTS idx_personas_nombre_trgm
    ON personas USING gin (build_nombre_completo(nombres, ap_pat, ap_mat) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_personas_nombre_busqueda_trgm
    ON personas USING gin (build_nombre_busqueda(ap_pat, ap_mat, nombres) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_personas_dni_like
    ON personas (dni text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_personas_ap_pat_soundex
    ON personas (ap_pat_soundex);

CREATE INDEX IF NOT EXISTS idx_personas_ap_pat_norm
    ON personas (immutable_unaccent(lower(ap_pat)) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_personas_ap_mat_norm
    ON personas (immutable_unaccent(lower(ap_mat)) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_personas_nombres_norm
    ON personas (immutable_unaccent(lower(nombres)) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_personas_padre_norm
    ON personas (immutable_unaccent(lower(padre)) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_personas_madre_norm
    ON personas (immutable_unaccent(lower(madre)) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_personas_fecha_nac
    ON personas (fecha_nac);

CREATE INDEX IF NOT EXISTS idx_auditoria_fecha
    ON auditoria_consultas (fecha DESC);
