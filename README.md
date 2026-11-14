# Buscador de Personas

Plataforma de consulta y búsqueda de personas sobre un padrón PostgreSQL, con API FastAPI, autenticación por cookie HttpOnly, búsqueda familiar con niveles de confianza y frontend estático sin dependencias.

> **Aviso:** la ficha C4 que genera este proyecto es un **documento de referencia no oficial**. No es un certificado de RENIEC y no tiene validez legal.

---

## Características principales

- **Búsqueda indexada**: PostgreSQL con `pg_trgm`, `unaccent`, `search_vector` ponderado e índices normalizados para apellidos y nombres.
- **Búsqueda familiar precisa**: padre, madre, abuelos, hermanos e hijos con puntuación de evidencia, nivel de confianza (`alta`/`media`/`baja`), alternativas y advertencias cuando no hay certeza suficiente.
- **Hermanos completos y medios hermanos**: distingue `hermano_completo`, `medio_hermano_paterno` y `medio_hermano_materno` según los campos de filiación.
- **Autenticación segura**: JWT en cookie `HttpOnly` + `SameSite=Strict`, con fallback `Bearer` para clientes API. El frontend nunca guarda el token en `localStorage`.
- **API keys de solo lectura**: las integraciones con `X-API-Key` no pueden acceder a endpoints de administración.
- **Cuotas atómicas**: descuento y reembolso de consultas ante errores o resultados no encontrados, con el saldo restante en `X-Consultas-Restantes` para que el frontend no haga peticiones extra.
- **Caché opcional con Redis**: si no hay `REDIS_URL`, se usa caché en memoria. Las claves de búsqueda se normalizan (tildes incluidas) y los DNI inexistentes se recuerdan brevemente para evitar consultas repetidas.
- **Ficha C4 de referencia**: claramente etiquetada como no oficial, sin logotipos ni leyendas de RENIEC.
- **Exportación CSV/JSON** con protección contra inyección de fórmulas.
- **Interfaz productiva**: vista de tarjetas o tabla ordenable, panel de detalle redimensionable y colapsable, estado compartible en la URL, enlaces directos por DNI (`?dni=12345678`), historial real del navegador y atajos de teclado (`/`, `↑`/`↓`, `T`, `C`, `Ctrl+K`, `?`). La búsqueda rápida se navega con `↑`/`↓` y se abre con `Enter`.
- **Accesibilidad**: enlace para saltar a la búsqueda, foco visible, diálogos con `aria-modal`/`inert`, cierre con `Escape`, trampa de foco, búsqueda rápida con patrón combobox/listbox, tarjetas con botón principal real sin controles anidados y panel de administración operable por teclado.
- **Árbol familiar eficiente**: render progresivo por lotes, caché de cinco minutos, vista de grafo o lista por pestañas y controles táctiles de 44 px.
- **Rendimiento móvil**: tipografía Inter local, `content-visibility`, `100dvh`, áreas seguras, acciones de 44 px y ampliación del área táctil de los iconos pequeños sin cambiar su tamaño visual, con animaciones desactivadas si el usuario prefiere menos movimiento.
- **PWA** con Service Worker stale-while-revalidate, aviso de actualización y sin caché de respuestas personales o autenticadas.
- **Caché de estáticos**: assets versionados con `immutable`, fuentes y SVG con caché semanal, y shell HTML/service worker siempre revalidables, también cuando FastAPI sirve el frontend sin Nginx.
- **Caché de búsquedas**: resultados principales y de búsqueda rápida en memoria durante 3-5 minutos, acotados por número de entradas y limpiados al cerrar sesión o expirar la cookie.
- **Resiliencia de red**: timeout de 25 s en las llamadas API, aborto de búsquedas obsoletas, mensajes claros de espera agotada y compresión gzip para respuestas JSON grandes.

---

## Stack tecnológico

| Capa | Tecnologías |
|---|---|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, HTTPX |
| **Base de datos** | PostgreSQL 16 (`pg_trgm`, `unaccent`, `fuzzystrmatch`, GIN y B-Tree) |
| **Frontend** | HTML5, CSS3, JavaScript ES6+ sin frameworks |
| **Infraestructura** | Docker, Docker Compose, Nginx, GitHub Actions |

---

## Despliegue con Docker

El compose de producción **no publica** los puertos de PostgreSQL ni del backend. Solo Nginx queda expuesto.

```bash
# 1. Clonar el repositorio
git clone https://github.com/Gustavo34555/buscador-personas.git
cd buscador-personas

# 2. Crear el archivo .env de la raíz a partir del ejemplo de Docker
cp .env.example .env
```

Edita `.env` y como mínimo define:

```dotenv
APP_ENV=production
POSTGRES_DB=buscador_personas
POSTGRES_USER=buscador
POSTGRES_PASSWORD=una_password_larga_y_unica
DATABASE_URL=postgresql+psycopg2://buscador:una_password_larga_y_unica@db:5432/buscador_personas
JWT_SECRET=un_secreto_de_al_menos_32_caracteres
ADMIN_PASSWORD=una_password_de_administrador_distinta
ALLOW_OPEN_ACCESS=false
COOKIE_SECURE=false   # cámbialo a true cuando sirvas por HTTPS
FRONTEND_PORT=8080
```

Genera el secreto JWT con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Levanta los servicios:

```bash
docker compose up -d --build
```

- **Frontend**: http://localhost:8080
- **API**: solo accesible a través de Nginx en `/persona`, `/buscar`, `/scraping`, `/api`, `/docs`.
- **PostgreSQL**: sin puerto publicado.

Para producción real, coloca Nginx detrás de HTTPS (por ejemplo con Caddy, Traefik o un certificado gestionado) y activa `COOKIE_SECURE=true`.

### Volumen de base de datos existente

`docker/initdb.sql` solo se ejecuta al crear un volumen nuevo. Para una base existente aplica las migraciones:

```bash
# 001 crea usuarios, token_version y la función de búsqueda.
# psql no entiende el prefijo "+psycopg2" del DATABASE_URL de SQLAlchemy.
psql "${DATABASE_URL/postgresql+psycopg2/postgresql}" \
  -f backend/migrations/001_auth_y_esquema.sql

# 002 crea índices normalizados de forma concurrente.
# Debe ejecutarlo el propietario de la tabla o un superusuario.
psql -U postgres -d buscador_personas \
  -f backend/migrations/002_indices_concurrentes.sql
```

> **Importante:** si la tabla `personas` pertenece a `postgres`, el usuario de la aplicación (por ejemplo `buscador` en Docker) no puede crear índices sobre ella. Ejecuta la migración 002 como `postgres` o pide al propietario que la aplique. La aplicación funciona sin esos índices, pero la búsqueda familiar y por apellidos será más lenta.

---

## Desarrollo local

### Requisitos

- Python 3.12+
- PostgreSQL 15+ con `pg_trgm`, `unaccent` y `fuzzystrmatch`

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env
# Edita .env: DATABASE_URL local, JWT_SECRET y ADMIN_PASSWORD

uvicorn app.main:app --reload --port 8000
```

El frontend puede servirse con Nginx o con cualquier servidor estático apuntando a `frontend/`. La API debe quedar en el mismo origen que el frontend; el `docker/nginx.conf` ya hace el proxy.

### Pruebas y linteo

```bash
cd backend
pytest -q          # 63 pruebas
ruff check .

# Smoke tests de interfaz (escritorio y móvil) con jsdom
cd ../frontend/tests
npm install
npm test
```

---

## Endpoints de la API

| Método | Endpoint | Descripción |
|---|---|---|
| POST | `/api/auth/login` | Login; guarda el JWT en cookie HttpOnly |
| POST | `/api/auth/logout` | Elimina la cookie de sesión |
| GET | `/api/auth/me` | Datos y cuota del usuario autenticado |
| GET | `/api/admin/usuarios` | Listado de usuarios (solo admin) |
| POST | `/api/admin/usuarios` | Crear usuario (solo admin) |
| PUT | `/api/admin/usuarios/{id}` | Actualizar cuota, estado o contraseña (solo admin) |
| DELETE | `/api/admin/usuarios/{id}` | Eliminar usuario (solo admin) |
| GET | `/persona/{dni}` | Consulta una persona por DNI |
| GET | `/buscar?q={texto}&limit=20` | Búsqueda ponderada por nombres o apellidos |
| GET | `/persona/{dni}/arbol?limite=200` | Árbol familiar con confianza, evidencia y alternativas (máximo 200 por relación) |
| GET | `/persona/{dni}/c4` | Ficha de referencia no oficial |
| GET | `/scraping/ruc/{dni}` | Consulta de RUC en SUNAT |
| GET | `/api/status` | Healthcheck con ping a PostgreSQL |

La API acepta autenticación por cookie (`bp_access`), por `Authorization: Bearer <token>` o por `X-API-Key` para integraciones de solo lectura. El modo abierto sin credenciales solo funciona con `ALLOW_OPEN_ACCESS=true` y sin `API_KEYS` configuradas.

---

## Seguridad

- Secretos obligatorios y validados al arrancar en `APP_ENV=production`.
- Contraseñas con bcrypt y límite de 72 bytes.
- Rate limiting separado para login, búsqueda y RUC.
- Cookies `HttpOnly`, `SameSite=Strict` y `Secure` cuando se sirve por HTTPS.
- API keys sin rol de administrador.
- Consultas SQL parametrizadas y errores internos sin trazas expuestas.
- CSP estricta sin scripts inline, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` y HSTS (con HTTPS).
- `Cache-Control: no-store` en respuestas con datos personales, de búsqueda y autenticación.
- `Server-Timing` y `X-Request-ID` para medir y correlacionar latencia.

---

## Contacto y licenciamiento

- **Desarrollador / Autor**: [Gustavo34555](https://github.com/Gustavo34555)
- **Repositorio**: https://github.com/Gustavo34555/buscador-personas

Este proyecto está bajo términos y condiciones de uso privado y licenciamiento de software. Consulta con el autor para acuerdos comerciales o despliegues en producción.
