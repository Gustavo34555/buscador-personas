# Buscador de Personas — Backend

API FastAPI para consultar el padrón de identificación (37M registros) y datos RUC SUNAT.

## Estructura

```
backend/
  app/
    main.py            # App FastAPI, CORS, middleware de seguridad, lifespan, frontend estático
    config.py          # Settings desde .env (fail-fast en producción)
    db.py              # Engine SQLAlchemy
    security.py        # JWT (cookie HttpOnly / Bearer), API keys y bcrypt
    dependencies.py    # IP real del cliente, rate limiters y usuario autenticado
    cache.py           # TTLCache en memoria / Redis opcional
    rate_limit.py      # Rate limiter por IP con Retry-After
    routers/
      auth.py          # login, logout y /api/auth/me
      admin.py         # gestión de usuarios (solo rol admin)
      persona.py       # consulta por DNI, búsqueda y árbol familiar
      ruc.py           # consultas RUC SUNAT
    services/
      auth_service.py      # login, JWT, sesiones y cuotas
      familia_service.py   # árbol familiar, evidencia y niveles de confianza
      persona_service.py   # consulta y búsqueda de personas
      ruc_service.py       # RUC
      auditoria_service.py # auditoría de consultas
    errors.py          # errores de dominio compartidos (consultas canceladas/fallidas)
    sql/queries.py     # SQL centralizado
  migrations/          # 001_auth_y_esquema.sql, 002_indices_concurrentes.sql, 003_search_schema.sql
  scripts/
    verificar_db.py      # Valida extensiones, índices y funciones de la DB
    prueba_busqueda.py   # Smoke test contra la DB real
  tests/               # pytest (68 pruebas con DB mockeada)
```

## Requisitos y configuración

- Python 3.12+, PostgreSQL 16 con `pg_trgm`, `unaccent` y `fuzzystrmatch`. Redis 7 es opcional: sin `REDIS_URL` se usa caché en memoria.
- Copia `../.env.example` a `../.env` si levantas el stack con Docker Compose, o `.env.example` a `.env` dentro de `backend/` para desarrollo local. Revisa **`backend/.env.example`** y **`.env.example`** (raíz) para ver todas las variables.

Variables principales:

- `DATABASE_URL` — conexión PostgreSQL (prefijo `postgresql+psycopg2://`). En Compose se reconstruye desde `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` para evitar divergencias.
- `JWT_SECRET` — obligatorio y seguro en producción; `JWT_COOKIE_NAME=bp_access`.
- `COOKIE_SECURE` — `true` cuando se sirve por HTTPS (`APP_ENV=production` exige HTTPS); en el ejemplo de desarrollo está en `false`.
- `API_KEYS` — claves de solo lectura separadas por coma.
- `ALLOW_OPEN_ACCESS` — acceso sin credenciales; prohibido en producción.
- `ALLOWED_ORIGINS`, `RUC_API_KEY`, `TRUST_PROXY_HEADERS`, `TRUSTED_PROXIES`, `REDIS_URL` — CORS, SUNAT, IP real del cliente y caché.

## Arranque

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
venv/bin/uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Docs: http://127.0.0.1:8000/docs
- Healthcheck: `GET /api/status` (verifica conexión a PostgreSQL)
- Frontend (sirve desde la raíz si existe `../frontend`): http://127.0.0.1:8000

## Autenticación

Los endpoints de datos aceptan tres formas de credencial, resueltas en `app/security.py`:

1. **JWT en cookie HttpOnly** `bp_access` (configurable con `JWT_COOKIE_NAME`), con `SameSite=Strict` y `Secure` cuando `COOKIE_SECURE=true`. Es la forma que usa el frontend: el navegador guarda la cookie, JavaScript no puede leerla y no se almacena ningún token en `localStorage`.
2. **JWT `Authorization: Bearer <token>`** para clientes API o scripts.
3. **API key de solo lectura** mediante `X-API-Key: <una de API_KEYS>`. El principal resultante tiene `rol=user` y `scope=data:read`: nunca puede acceder a `/api/admin/*` ni modificar datos.

`POST /api/auth/login` emite el JWT, `/api/auth/logout` revoca la cookie y `GET /api/auth/me` devuelve identidad y cuota. Las sesiones se validan contra `usuarios.token_version`, por lo que los tokens de usuarios desactivados o con la contraseña cambiada quedan invalidados.

El modo sin credenciales solo existe si `ALLOW_OPEN_ACCESS=true` y `API_KEYS` está vacío; `config.py` lo rechaza en producción. **Ya no existe una constante `API_KEY` en `frontend/app.js`**: las integraciones deben enviar su clave en la cabecera `X-API-Key`.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/auth/login` | Login; devuelve el JWT en cookie HttpOnly |
| POST | `/api/auth/logout` | Elimina/revoca la cookie de sesión |
| GET | `/api/auth/me` | Usuario autenticado y cuota restante |
| GET | `/api/admin/usuarios` | Listado de usuarios (solo admin) |
| POST | `/api/admin/usuarios` | Crear usuario (solo admin) |
| GET | `/persona/{dni}` | Datos completos de una persona por DNI |
| GET | `/buscar?q=...&limit=...` | Búsqueda ponderada por nombres o apellidos |
| GET | `/persona/{dni}/arbol?limite=...` | Árbol familiar con confianza y evidencia |
| GET | `/scraping/ruc/{dni}` | Consulta RUC de una persona por DNI |
| GET | `/scraping/ruc-info/{ruc}` | Detalle RUC SUNAT |
| GET | `/api/status` | Healthcheck (ping a PostgreSQL) |

Rate limit por IP (30/min en RUC, 60/min en búsqueda, 5/5 min en login) con header `Retry-After` en 429. Con `REDIS_URL` los contadores son atómicos y se comparten entre workers; sin Redis se usa un limitador en memoria. La IP real se toma de `X-Forwarded-For`/`X-Real-IP` solo si `TRUST_PROXY_HEADERS=true` y, cuando `TRUSTED_PROXIES` no está vacío, el socket pertenece a esa lista.

## Auditoría

Cada consulta se registra en `auditoria_consultas` con columnas `ip`, `tipo`, `query` y `fecha` (timestamp con zona horaria, índice `idx_auditoria_fecha`). No existe una columna `creado_en`.

## Base de datos

```bash
venv/bin/python scripts/verificar_db.py    # chequear setup
venv/bin/python scripts/prueba_busqueda.py # smoke test real
```

Para bases existentes aplica `migrations/001_auth_y_esquema.sql`, `migrations/002_indices_concurrentes.sql` y `migrations/003_search_schema.sql` con `psql` (la 002 y la 003 usan `CREATE INDEX CONCURRENTLY`, fuera de transacción). La 003 es imprescindible: crea `search_vector` y las columnas generadas que usan todas las consultas de búsqueda. En Docker, `docker/initdb.sql` ya crea el esquema al levantar un volumen nuevo.

## Tests

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest tests -q   # 68 pruebas
```
