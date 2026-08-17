# Buscador de Personas

Plataforma de alto rendimiento para la consulta, búsqueda y verificación de personas y registros tributarios, diseñada con arquitectura asíncrona, indexación ponderada en memoria y diseño web minimalista.

---

## Caracteristicas Principales

- **Motor de Busqueda Sub-15ms**: Algoritmo ponderado en PostgreSQL con pesos A/B/C (ap_pat > nombres > ap_mat), trigramas GIN y soporte fonetico (fuzzystrmatch).
- **Ficha Digital 3D**: Visualizacion interactiva tipo tarjeta inteligente con codigo de seguridad MRZ, avatar de genero y cronologia de vigencia.
- **Arbol y Busqueda Familiar**: Navegacion en un clic hacia la ficha de los familiares de cualquier persona.
- **Consulta de RUC en Tiempo Real**: Modulo de consulta tributaria con estado en vivo (Activo/Habido), condicion y domicilio fiscal.
- **Seguridad y Resiliencia**: Tokens de sesion temporales HMAC, rate limiting en memoria, proteccion contra timing attacks y headers de seguridad HTTP.
- **Exportacion de Datos**: Descarga de resultados en formatos estructurados CSV (Excel) y JSON, ademas de vista optimizada para impresion A4.
- **PWA y Offline Shell**: Aplicacion web progresiva instalable en escritorio y dispositivos moviles con Service Worker y soporte para atajos de teclado (Ctrl+K, flechas arriba/abajo).

---

## Stack Tecnologico

| Capa | Tecnologias |
|---|---|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, HTTPX |
| **Base de Datos** | PostgreSQL 16 (pg_trgm, unaccent, fuzzystrmatch, B-Tree Covering Indexes) |
| **Frontend** | HTML5 Semantico, Vanilla CSS3 (Custom Design System, Dark Mode), JavaScript ES6+ Moderno |
| **Infraestructura** | Docker, Docker Compose, Nginx, GitHub Actions CI/CD |

---

## Despliegue con Docker

Para levantar el entorno completo (Base de Datos + Backend API + Frontend Web):

```bash
# 1. Clonar el repositorio
git clone https://github.com/Gustavo34555/buscador-personas.git
cd buscador-personas

# 2. Configurar variables de entorno
cp backend/.env.example backend/.env

# 3. Iniciar todos los servicios
docker compose up -d --build
```

- **Frontend Web**: http://localhost
- **API Backend**: http://localhost:8000
- **Documentacion Swagger / OpenAPI**: http://localhost:8000/docs

---

## Desarrollo Local

### Requisitos
- Python 3.12+
- PostgreSQL 15+ con extensiones pg_trgm, unaccent, fuzzystrmatch

```bash
# Entrar al backend y crear entorno virtual
cd backend
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt -r requirements-dev.txt

# Configurar variables
cp .env.example .env

# Ejecutar servidor de desarrollo
uvicorn app.main:app --reload --port 8000
```

### Ejecutar Pruebas y Linteo
```bash
# Correr suite de tests automatizados (34 tests)
pytest

# Analisis estatico de codigo con Ruff
ruff check .
```

---

## Endpoints de la API

| Metodo | Endpoint | Descripcion |
|---|---|---|
| GET | `/persona/{dni}` | Consulta detallada de una persona por numero de documento (8 digitos) |
| GET | `/buscar?q={texto}&limit=20` | Busqueda difusa ponderada por nombres o apellidos |
| GET | `/scraping/ruc/{dni}` | Consulta del estado y datos de RUC tributario |
| GET | `/api/frontend-token` | Emision de token HMAC temporal para clientes autorizados |
| GET | `/api/status` | Healthcheck activo con ping a PostgreSQL |

---

## Contacto y Licenciamiento

Para implementaciones personalizadas, adquisicion del sistema, integraciones empresariales o soporte tecnico:

- **Desarrollador / Autor**: [Gustavo34555](https://github.com/Gustavo34555)
- **Repositorio**: https://github.com/Gustavo34555/buscador-personas

---

## Licencia

Este proyecto esta bajo los terminos y condiciones de uso privado y licenciamiento de software. Consulte con el autor para acuerdos comerciales o despliegues en produccion.
