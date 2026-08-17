-- Ajustes de PostgreSQL para 15 GB RAM / 12 núcleos / NVMe (laptop del dev)
-- Uso: cat scripts/tuning_postgres.sql | sudo -u postgres psql
--
-- shared_buffers requiere REINICIO del servicio:
--   sudo systemctl restart postgresql

ALTER SYSTEM SET shared_buffers = '4GB';                -- era 1GB (requiere restart)
ALTER SYSTEM SET effective_cache_size = '10GB';         -- era 4GB
ALTER SYSTEM SET work_mem = '32MB';                     -- era 4MB
ALTER SYSTEM SET maintenance_work_mem = '1GB';          -- era 64MB
ALTER SYSTEM SET random_page_cost = 1.1;                -- era 4 (NVMe, no HDD)
ALTER SYSTEM SET effective_io_concurrency = 200;        -- era 1
ALTER SYSTEM SET max_parallel_workers_per_gather = 4;   -- era 2
ALTER SYSTEM SET max_parallel_workers = 8;

SELECT pg_reload_conf();
