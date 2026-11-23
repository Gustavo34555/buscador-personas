# Buscador de Personas

Plataforma de consulta y búsqueda de personas sobre un padrón PostgreSQL de aproximadamente 37 millones de registros. Expone una API FastAPI con autenticación por cookie HttpOnly, búsqueda familiar con niveles de confianza y un frontend estático sin frameworks.

## Características

- Búsqueda indexada con PostgreSQL: extensiones `pg_trgm`, `unaccent` y `fuzzystrmatch`, `search_vector` ponderado, índices GIN y B-Tree sobre campos normalizados.
- Búsqueda por DNI o por nombre completo con re-ranking de precisión: coincidencia exacta, prefijos, orden de tokens y similitud trigramétrica.
- Árbol familiar con padre, madre, abuelos, hermanos e hijos. Cada relación incluye evidencia, nivel de confianza (`alta`, `media` o `baja`), candidatos alternativos y advertencias cuando la evidencia es insuficiente.
- Diferenciación entre hermano completo, medio hermano paterno y medio hermano materno según los campos de filiación.
- Caché de búsqueda, búsqueda rápida y árbol en el cliente, con expiración y limpieza al cerrar sesión. El servidor mantiene caché en memoria o Redis compartido entre workers.
- Cuotas atómicas por usuario. Cada respuesta incluye el saldo en `X-Consultas-Restantes`. Los errores, timeouts y resultados no encontrados reembolsan la consulta.
- Autenticación con JWT en cookie HttpOnly y `SameSite=Strict`, con soporte opcional para `Authorization: Bearer`. Las API keys permiten acceso de solo lectura y no pueden administrar usuarios.
- Protección CSRF mediante cabecera personalizada cuando `COOKIE_SAMESITE=none`.
- Exportación CSV y JSON con protección contra inyección de fórmulas.
- Interfaz adaptable con vista de tarjetas o tabla, panel de detalle redimensionable, estado compartible en la URL, enlaces directos por DNI, historial del navegador y atajos de teclado (`/`, `↑`/`↓`, `T`, `Ctrl+K`, `?`).
- Accesibilidad: enlace de salto, foco visible, diálogos con `aria-modal` e `inert`, trampa de foco, cierre con `Escape`, patrón combobox/listbox en la búsqueda rápida y controles táctiles de 44 px.
- PWA con Service Worker, aviso de nueva versión y exclusión de respuestas personales o autenticadas de la caché.
- Tipografías Inter y Material Symbols alojadas localmente, sin dependencias de terceros en el critical path.

## Stack tecnológico

| Capa | Tecnologías |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, HTTPX |
| Base de datos | PostgreSQL 16 con `pg_trgm`, `unaccent` y `fuzzystrmatch` |
| Caché | Memoria local o Redis 7 |
| Frontend | HTML5, CSS3, JavaScript ES6+ sin frameworks |
| Infraestructura | Docker, Docker Compose, Nginx, GitHub Actions |

## Despliegue con Docker Compose

El stack no publica los puertos de PostgreSQL, Redis ni del backend. Solo Nginx queda expuesto en `FRONTEND_PORT` (8080 por defecto). El backend espera a que PostgreSQL y Redis estén sanos antes de arrancar, y Nginx espera al healthcheck del backend.

```bash
git clone https://github.com/Gustavo34555/buscador-personas.git
cd buscador-personas
cp .env.example .env
```

Edita `.env` y define al menos las siguientes variables:

```dotenv
APP_ENV=production
POSTGRES_DB=buscador_personas
POSTGRES_USER=buscador
POSTGRES_PASSWORD=contrasena_larga_y_unica
DATABASE_URL=postgresql+psycopg2://buscador:contrasena_larga_y_unica@db:5432/buscador_personas
JWT_SECRET=secreto_de_al_menos_32_caracteres
ADMIN_PASSWORD=contrasena_de_administrador_distinta
ALLOW_OPEN_ACCESS=false
COOKIE_SECURE=true
REDIS_URL=redis://redis:6379/0
FRONTEND_PORT=8080
```

`DATABASE_URL` debe repetir exactamente la contraseña de `POSTGRES_PASSWORD`. Puedes comprobarlo con `make check-env`. En Docker Compose el backend reconstruye la URL desde `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB`; el valor de `.env` se reserva para `psql` y las migraciones en local.

Genera `JWT_SECRET` con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Levanta el stack:

```bash
docker compose up -d --build
```

Servicios disponibles:

- Frontend: `http://localhost:8080`
- API: a través de Nginx en `/persona`, `/buscar`, `/scraping`, `/api` y `/docs`
- PostgreSQL y Redis: sin puertos publicados

Para producción termina TLS en un proxy externo (Caddy, Traefik o un certificado gestionado) y mantén `COOKIE_SECURE=true`. Nginx emite HSTS en todas las respuestas, pero el navegador solo la aplica si la petición llega por HTTPS. Si cambias la subred `172.28.0.0/16` del compose, actualiza también `FORWARDED_ALLOW_IPS` y `TRUSTED_PROXIES`.

### Bases de datos existentes

`docker/initdb.sql` solo se ejecuta al crear un volumen nuevo. Para una base ya creada, aplica las migraciones en orden:

```bash
DATABASE_URL_PSQL="${DATABASE_URL/postgresql+psycopg2/postgresql}"

psql "$DATABASE_URL_PSQL" -v ON_ERROR_STOP=1 -f backend/migrations/001_auth_y_esquema.sql
psql "$DATABASE_URL_PSQL" -v ON_ERROR_STOP=1 -f backend/migrations/002_indices_concurrentes.sql
psql "$DATABASE_URL_PSQL" -v ON_ERROR_STOP=1 -f backend/migrations/003_search_schema.sql
```

La migración 002 y la 003 usan `CREATE INDEX CONCURRENTLY` y deben ejecutarse fuera de una transacción. La 003 crea `search_vector` y las columnas generadas que utilizan todas las consultas de búsqueda; sin ella la búsqueda devuelve cero resultados. Si la tabla `personas` pertenece a otro rol, las migraciones de índices deben ejecutarlas el propietario o un superusuario.

## Desarrollo local

Requisitos: Python 3.12+, PostgreSQL 16 con las extensiones indicadas y Redis 7 opcional.

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Configura `DATABASE_URL`, `JWT_SECRET` y `ADMIN_PASSWORD` en `backend/.env`, y arranca la API:

```bash
uvicorn app.main:app --reload --port 8000
```

El frontend puede servirse con Nginx o con cualquier servidor estático apuntando a `frontend/`. La API debe estar en el mismo origen; `docker/nginx.conf` incluye el proxy correspondiente.

### Pruebas y linteo

```bash
cd backend
pytest -q
ruff check .

cd ../frontend/tests
npm ci
npm test
```

La suite backend contiene 75 pruebas. Los smoke tests de interfaz cubren escritorio y móvil con jsdom, y verifican también que las versiones de `index.html` y del Service Worker sean coherentes.

## Integración continua

`.github/workflows/ci.yml` ejecuta tres jobs en cada push y pull request:

- `backend`: Ruff y pytest.
- `frontend`: comprobación de sintaxis de los archivos JavaScript, `npm ci` y smoke tests de escritorio y móvil.
- `integration`: levanta PostgreSQL 16, aplica `docker/initdb.sql` y las migraciones 001, 002 y 003, y verifica columnas e índices.

## Endpoints de la API

| Método | Endpoint | Descripción |
| --- | --- | --- |
| POST | `/api/auth/login` | Inicia sesión y devuelve el JWT en cookie HttpOnly |
| POST | `/api/auth/logout` | Elimina la cookie de sesión |
| GET | `/api/auth/me` | Identidad y cuota del usuario autenticado |
| GET | `/api/admin/usuarios` | Listado de usuarios (solo administradores) |
| POST | `/api/admin/usuarios` | Crea un usuario (solo administradores) |
| PUT | `/api/admin/usuarios/{id}` | Actualiza cuota, estado o contraseña (solo administradores) |
| DELETE | `/api/admin/usuarios/{id}` | Elimina un usuario (solo administradores) |
| GET | `/persona/{dni}` | Datos completos de una persona por DNI |
| GET | `/buscar?q={texto}&limit=20` | Búsqueda ponderada por nombres o apellidos |
| GET | `/persona/{dni}/arbol?limite=200` | Árbol familiar con confianza, evidencia y alternativas |
| GET | `/scraping/ruc/{dni}` | Consulta de RUC en SUNAT |
| GET | `/api/status` | Healthcheck con ping a PostgreSQL |

La API acepta cookie `bp_access`, `Authorization: Bearer <token>` o `X-API-Key` para integraciones de solo lectura. El modo abierto sin credenciales solo funciona con `ALLOW_OPEN_ACCESS=true` y sin `API_KEYS` configuradas.

## Seguridad

- Validación fail-fast de secretos cuando `APP_ENV=production`.
- Contraseñas con bcrypt y límite explícito de 72 bytes.
- Rate limiting independiente para login, búsqueda y RUC, con `Retry-After` en las respuestas 429. Con Redis los contadores son atómicos y se comparten entre workers.
- Solo se confían cabeceras `X-Forwarded-For` y `X-Real-IP` cuando `TRUST_PROXY_HEADERS=true` y la IP del socket pertenece a `TRUSTED_PROXIES`.
- Consultas SQL parametrizadas. Los errores de base de datos devuelven 503 o 504 con reembolso de cuota, en lugar de presentarse como resultados vacíos.
- Auditoría con hash del término buscado en lugar del texto literal. Los logs se emiten como JSON válido y el `X-Request-ID` se valida antes de reflejarse.
- Cabeceras `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` y HSTS. La CSP permite estilos en línea por el marcado generado en el cliente, pero restringe scripts y fuentes al mismo origen.
- `Cache-Control: no-store` en respuestas con datos personales, búsqueda y autenticación.
- `Server-Timing` y `X-Request-ID` para medir y correlacionar latencia.

## Autor y licenciamiento

Desarrollador: [Gustavo34555](https://github.com/Gustavo34555)

Repositorio: https://github.com/Gustavo34555/buscador-personas

El proyecto se distribuye bajo términos de uso privado. Consulta con el autor para acuerdos comerciales o despliegues en producción.
