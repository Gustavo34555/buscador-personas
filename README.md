# 🇵🇪 Buscador de Personas & Padrón Nacional

Plataforma de alto rendimiento para la consulta, búsqueda y análisis de información de identificación nacional (DNI/Reniec) y registros tributarios (RUC/SUNAT), diseñada con arquitectura asíncrona, indexación ponderada en memoria y diseño web ultra-premium.

---

## ⚡ Características Principales

- **🚀 Motor de Búsqueda Sub-15ms**: Algoritmo ponderado en PostgreSQL con pesos A/B/C (`ap_pat > nombres > ap_mat`), trigramas GIN y soporte fonético (`fuzzystrmatch`).
- **💳 Ficha Digital DNI 3D**: Visualización interactiva tipo tarjeta inteligente con código de seguridad MRZ, avatar de género y cronología de vigencia.
- **👨‍👩‍👧 Árbol y Búsqueda Familiar**: Navegación en un clic hacia la ficha de los padres de cualquier persona.
- **🏛️ Consulta SUNAT en Tiempo Real**: Módulo de scraping/API de RUC con estado tributario (Activo/Habido), condición y domicilio fiscal.
- **🔒 Seguridad & Resiliencia**: Tokens de sesión temporales HMAC, rate limiting en memoria, protección contra timing attacks y headers de seguridad HTTP.
- **📊 Exportación de Datos**: Descarga de resultados en formatos estructurados **CSV** (Excel) y **JSON**, además de vista optimizada para impresión A4.
- **📱 PWA & Offline Shell**: Aplicación web progresiva instalable en escritorio y dispositivos móviles con Service Worker y soporte para atajos de teclado (`Ctrl+K`, flechas `↑`/`↓`).

---

## 🛠️ Stack Tecnológico

| Capa | Tecnologías |
|---|---|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, HTTPX |
| **Base de Datos** | PostgreSQL 16 (`pg_trgm`, `unaccent`, `fuzzystrmatch`, B-Tree Covering Indexes) |
| **Frontend** | HTML5 Semántico, Vanilla CSS3 (Custom Design System, Dark Mode), JavaScript ES6+ Moderno |
| **Infraestructura** | Docker, Docker Compose, Nginx, GitHub Actions CI/CD |

---

## 🚀 Despliegue Rápido con Docker

La forma más rápida de levantar el entorno completo (Base de Datos + Backend API + Frontend Web):

```bash
# 1. Clonar el repositorio
git clone https://github.com/Gustavo34555/buscador-personas.git
cd buscador-personas

# 2. Configurar variables de entorno
cp backend/.env.example backend/.env

# 3. Iniciar todos los servicios
docker compose up -d --build
```

- **Frontend Web**: [http://localhost](http://localhost)
- **API Backend**: [http://localhost:8000](http://localhost:8000)
- **Documentación Swagger / OpenAPI**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 💻 Desarrollo Local

### Requisitos
- Python 3.12+
- PostgreSQL 15+ con extensiones `pg_trgm`, `unaccent`, `fuzzystrmatch`

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

# Análisis estático de código con Ruff
ruff check .
```

---

## 📡 Endpoints de la API

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/persona/{dni}` | Consulta detallada de una persona por número de DNI (8 dígitos) |
| `GET` | `/buscar?q={texto}&limit=20` | Búsqueda difusa ponderada por nombres o apellidos |
| `GET` | `/scraping/ruc/{dni}` | Consulta del estado y datos de RUC ante SUNAT |
| `GET` | `/api/frontend-token` | Emisión de token HMAC temporal para clientes autorizados |
| `GET` | `/api/status` | Healthcheck activo con ping a PostgreSQL |

---

## 💼 Contacto y Consultoría de Software

Para implementaciones personalizadas, licenciamiento del sistema, integraciones empresariales o soporte técnico:

- **Desarrollador / Autor**: [Gustavo34555](https://github.com/Gustavo34555)
- **Repositorio**: [https://github.com/Gustavo34555/buscador-personas](https://github.com/Gustavo34555/buscador-personas)

---

## 📄 Licencia

Este proyecto está bajo los términos y condiciones de uso privado y licenciamiento de software. Consulte con el autor para acuerdos comerciales o despliegues en producción.
