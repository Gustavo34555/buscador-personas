-- Inicialización de PostgreSQL para el Buscador de Personas
-- Se ejecuta automáticamente al levantar el contenedor de Docker

-- 1. Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- 2. Función unaccent inmutable para índices y consultas rápidas
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text AS $$
    SELECT public.unaccent(public.unaccent($1))
$$ LANGUAGE sql IMMUTABLE STRICT;

-- 3. Funciones auxiliares para construir nombres en minúsculas y sin acentos
CREATE OR REPLACE FUNCTION build_nombre_completo(nombres text, ap_pat text, ap_mat text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(' ', trim(coalesce(nombres, '')), trim(coalesce(ap_pat, '')), trim(coalesce(ap_mat, ''))))))
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION build_nombre_busqueda(ap_pat text, ap_mat text, nombres text)
RETURNS text AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(' ', trim(coalesce(ap_pat, '')), trim(coalesce(ap_mat, '')), trim(coalesce(nombres, ''))))))
$$ LANGUAGE sql IMMUTABLE;

-- 4. Tabla principal de personas
CREATE TABLE IF NOT EXISTS personas (
    dni VARCHAR(8) PRIMARY KEY,
    ap_pat VARCHAR(100),
    ap_mat VARCHAR(100),
    nombres VARCHAR(150),
    fecha_nac DATE,
    fch_emision DATE,
    fch_inscripcion DATE,
    fch_caducidad DATE,
    direccion TEXT,
    ubigeo_nac VARCHAR(10),
    ubigeo_dir VARCHAR(10),
    sexo VARCHAR(20),
    est_civil VARCHAR(50),
    padre VARCHAR(200),
    madre VARCHAR(200),
    dig_ruc VARCHAR(2),
    -- Columnas precalculadas para evitar overhead en CPU (orden formal y orden natural)
    nombre_completo TEXT GENERATED ALWAYS AS (
        lower(immutable_unaccent(trim(coalesce(nombres, '')) || ' ' || trim(coalesce(ap_pat, '')) || ' ' || trim(coalesce(ap_mat, ''))))
    ) STORED,
    nombre_busqueda TEXT GENERATED ALWAYS AS (
        lower(immutable_unaccent(trim(coalesce(ap_pat, '')) || ' ' || trim(coalesce(ap_mat, '')) || ' ' || trim(coalesce(nombres, ''))))
    ) STORED,
    -- Representación fonética de apellidos paternos para tolerancia a variantes
    ap_pat_soundex TEXT GENERATED ALWAYS AS (
        soundex(immutable_unaccent(coalesce(ap_pat, '')))
    ) STORED,
    -- Vector ponderado: Apellido Paterno (A=1.0), Nombres (B=0.4), Materno (C=0.2)
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(ap_pat, ''))), 'A') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(nombres, ''))), 'B') ||
        setweight(to_tsvector('simple', immutable_unaccent(coalesce(ap_mat, ''))), 'C')
    ) STORED
);

-- 5. Tabla de auditoría
CREATE TABLE IF NOT EXISTS auditoria_consultas (
    id SERIAL PRIMARY KEY,
    ip VARCHAR(45) NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    query VARCHAR(500) NOT NULL,
    fecha TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Índices optimizados para Index-Only Scan, Trigramas y Búsqueda Fonética
CREATE INDEX IF NOT EXISTS idx_personas_search_vector 
    ON personas USING gin (search_vector);

CREATE INDEX IF NOT EXISTS idx_personas_nombre_trgm
    ON personas USING gin (nombre_completo gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_personas_nombre_busqueda_trgm
    ON personas USING gin (nombre_busqueda gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_personas_dni_like
    ON personas (dni text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_personas_ap_pat_soundex
    ON personas (ap_pat_soundex);

CREATE INDEX IF NOT EXISTS idx_personas_ap_pat_lower
    ON personas (lower(ap_pat) text_pattern_ops) INCLUDE (dni, nombres, ap_mat);

CREATE INDEX IF NOT EXISTS idx_personas_nombres_lower
    ON personas (lower(nombres) text_pattern_ops) INCLUDE (dni, ap_pat, ap_mat);

CREATE INDEX IF NOT EXISTS idx_personas_ap_mat_lower
    ON personas (lower(ap_mat) text_pattern_ops) INCLUDE (dni, nombres, ap_pat);

CREATE INDEX IF NOT EXISTS idx_auditoria_fecha
    ON auditoria_consultas (fecha DESC);
