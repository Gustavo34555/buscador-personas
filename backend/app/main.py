import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import ALLOWED_ORIGINS, COOKIE_SECURE, RUC_API_KEY
from app.db import engine
from app.routers import admin, auth, persona, ruc
from app.schemas import StatusResponse
from app.services import auth_service
from app.services.ruc_service import RucService


# Configurar logging estructurado básico
class JsonFormatter(logging.Formatter):
    """Serializa cada registro como JSON válido, incluso con comillas en el mensaje."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


logging.basicConfig(level=logging.INFO)
for _handler in logging.getLogger().handlers:
    _handler.setFormatter(JsonFormatter())
logger = logging.getLogger(__name__)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ruc_service = RucService(api_key=RUC_API_KEY)
    try:
        await asyncio.to_thread(auth_service.asegurar_admin)
    except Exception:
        logger.exception("No se pudo verificar el administrador inicial")
    yield
    await app.state.ruc_service.close()


app = FastAPI(title="Buscador de Personas API", lifespan=lifespan)


@app.middleware("http")
async def security_and_tracing_middleware(request: Request, call_next) -> Response:
    """Inyecta Request-ID, headers de seguridad y mide latencia de peticiones."""
    raw_request_id = request.headers.get("X-Request-ID", "")
    request_id = raw_request_id if _REQUEST_ID_RE.fullmatch(raw_request_id) else str(uuid.uuid4())
    start_time = time.perf_counter()

    response: Response = await call_next(request)

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # Headers de trazabilidad y seguridad HTTP
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "script-src 'self'; worker-src 'self'; manifest-src 'self'; "
        "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    response.headers["Server-Timing"] = f"app;dur={duration_ms}"
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Las respuestas con datos personales nunca deben quedar en cachés
    # compartidas, proxies ni en el historial de recursos del navegador.
    path = request.url.path
    if path.startswith(("/persona", "/buscar", "/scraping", "/api/")):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.query_params.get("v") and path.endswith((".css", ".js")):
        # Assets con versión en la URL: cacheables de forma inmutable.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/fonts/") or path.endswith((".woff2", ".woff", ".svg", ".png", ".ico")):
        response.headers["Cache-Control"] = "public, max-age=604800"
    else:
        # El shell HTML y el service worker deben revalidarse para recibir
        # actualizaciones, incluso si no hay Nginx delante de FastAPI.
        response.headers["Cache-Control"] = "no-cache"

    # Log estructurado con correlation id y duración
    if not request.url.path.startswith("/static"):
        logger.info(
            '{"req_id": "%s", "method": "%s", "path": "%s", "status": %d, "duration_ms": %.2f}',
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "X-Request-ID", "Server-Timing", "X-Consultas-Restantes"],
)

# Comprime JSON grandes (búsquedas, árboles) también cuando FastAPI se
# despliega sin Nginx. Nivel 6: buena relación tamaño/CPU.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(persona.router)
app.include_router(ruc.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Evita exponer trazas internas y registra el error con su Request-ID."""
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor"},
    )


@app.get("/api/status", response_model=StatusResponse)
async def status():
    """Healthcheck activo: verifica conexión a PostgreSQL."""
    try:

        def _ping():
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

        await asyncio.to_thread(_ping)
        return {"mensaje": "API operativa", "database": "ok"}
    except SQLAlchemyError as exc:
        logger.exception("Healthcheck falló al conectar a la base de datos")
        raise HTTPException(
            status_code=503,
            detail="Servicio no disponible: fallo en conexión a la base de datos",
        ) from exc


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    logger.warning("No se encontró el directorio frontend en %s", FRONTEND_DIR)
