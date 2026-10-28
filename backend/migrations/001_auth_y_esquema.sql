-- Migración rápida e idempotente para bases existentes.
-- Ejecutar con:
--   psql "${DATABASE_URL/postgresql+psycopg2/postgresql}" \
--     -f backend/migrations/001_auth_y_esquema.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- La tabla usuarios debe existir también en instalaciones nuevas.
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

-- Bases creadas antes de la revocación de tokens.
ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_usuarios_username ON usuarios (username);

-- Función de normalización inmutable. Debe existir antes de los índices
-- funcionales y de build_nombre_busqueda.
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text AS $$
    SELECT public.unaccent(public.unaccent($1))
$$ LANGUAGE sql IMMUTABLE STRICT;

-- Función de nombre en orden natural (nombres primero) sin acentos.
CREATE OR REPLACE FUNCTION build_nombre_completo(nombres text, ap_pat text, ap_mat text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(
        ' ',
        trim(coalesce(nombres, '')),
        trim(coalesce(ap_pat, '')),
        trim(coalesce(ap_mat, ''))
    ))))
$$;

-- Función de nombre en orden natural (apellidos primero) sin acentos.
-- Es importante que sea IMMUTABLE para poder indexarla.
CREATE OR REPLACE FUNCTION build_nombre_busqueda(ap_pat text, ap_mat text, nombres text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT lower(immutable_unaccent(trim(concat_ws(
        ' ',
        trim(coalesce(ap_pat, '')),
        trim(coalesce(ap_mat, '')),
        trim(coalesce(nombres, ''))
    ))))
$$;

-- Auditoría de consultas (también se crea en docker/initdb.sql).
CREATE TABLE IF NOT EXISTS auditoria_consultas (
    id SERIAL PRIMARY KEY,
    ip VARCHAR(45) NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    query VARCHAR(500) NOT NULL,
    fecha TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_auditoria_fecha
    ON auditoria_consultas (fecha DESC);
