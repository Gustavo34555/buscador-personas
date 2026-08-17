-- Índices y optimizaciones de alto rendimiento para búsqueda por nombre
-- Ejecutar como superusuario:
--   cat scripts/optimizar_busqueda.sql | sudo -u postgres psql -d buscador_personas

SET maintenance_work_mem = '2GB';

-- 1) Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- 2) Trigramas del nombre completo (typos y similitud)
CREATE INDEX IF NOT EXISTS idx_personas_nombre_trgm
    ON personas USING gin (build_nombre_completo(nombres, ap_pat, ap_mat) gin_trgm_ops);

-- 3) Prefijo de DNI en búsqueda por nombre
CREATE INDEX IF NOT EXISTS idx_personas_dni_like
    ON personas (dni text_pattern_ops);

-- 4) Buckets por componente con Index-Only Scan (INCLUDE)
CREATE INDEX IF NOT EXISTS idx_personas_ap_pat_lower
    ON personas (lower(ap_pat) text_pattern_ops) INCLUDE (dni, nombres, ap_mat);

CREATE INDEX IF NOT EXISTS idx_personas_nombres_lower
    ON personas (lower(nombres) text_pattern_ops) INCLUDE (dni, ap_pat, ap_mat);

CREATE INDEX IF NOT EXISTS idx_personas_ap_mat_lower
    ON personas (lower(ap_mat) text_pattern_ops);

-- 5) Actualizar estadísticas del optimizador de consultas
VACUUM ANALYZE personas;
