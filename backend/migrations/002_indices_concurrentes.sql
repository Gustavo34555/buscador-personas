-- Índices de apoyo para búsqueda familiar y búsqueda por nombre.
--
-- IMPORTANTE: CREATE INDEX CONCURRENTLY no puede ejecutarse dentro de una
-- transacción. Ejecutar este archivo directamente con psql:
--
--   psql "${DATABASE_URL/postgresql+psycopg2/postgresql}" \
--     -f backend/migrations/002_indices_concurrentes.sql
--
-- En una base de 37 millones de filas estos índices pueden tardar varios
-- minutos y ocupar espacio en disco. La aplicación funciona sin ellos, pero
-- las búsquedas por un único apellido/nombre común son más rápidas con ellos.

-- Apellido paterno normalizado (sin acentos, minúsculas).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_ap_pat_norm
    ON personas (immutable_unaccent(lower(ap_pat)) text_pattern_ops);

-- Apellido materno normalizado.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_ap_mat_norm
    ON personas (immutable_unaccent(lower(ap_mat)) text_pattern_ops);

-- Nombres normalizados.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_nombres_norm
    ON personas (immutable_unaccent(lower(nombres)) text_pattern_ops);

-- Campos de filiación normalizados. Sirven para localizar hijos/hermanos por
-- el nombre del progenitor cuando el apellido compartido es muy común.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_padre_norm
    ON personas (immutable_unaccent(lower(padre)) text_pattern_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_madre_norm
    ON personas (immutable_unaccent(lower(madre)) text_pattern_ops);

-- Rango de fechas para validar relaciones biológicas.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_personas_fecha_nac
    ON personas (fecha_nac);
