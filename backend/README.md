# Buscador de Personas — Backend

API FastAPI para consultar el padrón de identificación (37M registros) y datos RUC SUNAT.

## Estructura

```
backend/
  app/
    main.py          # App FastAPI, CORS, lifespan, static frontend
    config.py        # Settings desde .env
    db.py            # Engine SQLAlchemy
    security.py      # Autenticación con API key (X-API-Key)
    cache.py         # TTLCache LRU con lock
    rate_limit.py    # Rate limiter por IP con Retry-After
    routers/         # persona.py, ruc.py
    services/        # persona_service, ruc_service, auditoria_service
    sql/queries.py   # SQL centralizado
  scripts/
    verificar_db.py      # Valida extensiones, índices y funciones de la DB
    prueba_busqueda.py   # Smoke test contra la DB real
  tests/             # pytest (24+ tests con DB mockeada)
```

## Requisitos

- Python 3.12, PostgreSQL con extensiones `pg_trgm` y `unaccent`
- Copiar `.env` (ver `.env` del repo) con:
  - `DATABASE_URL` — conexión PostgreSQL
  - `API_KEYS` — claves aceptadas separadas por coma (vacío = acceso abierto, solo desarrollo)
  - `RUC_API_KEY` — key gratuita de https://peruapi.com/registro
  - `ALLOWED_ORIGINS` — orígenes CORS

## Arranque

```bash
venv/bin/pip install -r requirements.txt
venv/bin/uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Docs: http://127.0.0.1:8000/docs
- Frontend (sirve desde la raíz si existe `../frontend`): http://127.0.0.1:8000

## Autenticación

Todos los endpoints de datos exigen el header:

```
X-API-Key: <clave de API_KEYS en .env>
```

El frontend envía la misma clave (constante `API_KEY` en `frontend/app.js`).
Si `API_KEYS` está vacío, el acceso queda abierto (modo desarrollo).

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/persona/{dni}` | Datos completos de una persona por DNI |
| GET | `/buscar?q=...&limit=...` | Búsqueda por nombre (mínimo 3 caracteres) |
| GET | `/scraping/ruc/{dni}` | Consulta RUC de una persona por DNI |
| GET | `/scraping/ruc-info/{ruc}` | Detalle RUC SUNAT |
| GET | `/api/status` | Healthcheck |

Rate limit por IP (30/min en RUC, 60/min en personas) con header `Retry-After` en 429.

## Auditoría

Cada consulta se registra en `auditoria_consultas` (ip, tipo, query, creado_en).

## Base de datos

```bash
venv/bin/python scripts/verificar_db.py    # chequear setup
venv/bin/python scripts/prueba_busqueda.py # smoke test real
```

## Tests

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest tests -q
```
