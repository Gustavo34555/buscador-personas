import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import ALLOWED_ORIGINS, FRONTEND_TOKEN_SECRET, RUC_API_KEY
from app.db import engine
from app.routers import persona, ruc
from app.schemas import FrontendTokenResponse, StatusResponse
from app.security import create_frontend_token
from app.services.ruc_service import RucService

# Configurar logging estructurado básico
logging.basicConfig(
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ruc_service = RucService(api_key=RUC_API_KEY)
    yield
    await app.state.ruc_service.close()


app = FastAPI(title="Buscador de Personas API", lifespan=lifespan)


@app.middleware("http")
async def security_and_tracing_middleware(request: Request, call_next) -> Response:
    """Inyecta Request-ID, headers de seguridad y mide latencia de peticiones."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start_time = time.perf_counter()

    response: Response = await call_next(request)

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # Headers de trazabilidad y seguridad HTTP
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"

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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(persona.router)
app.include_router(ruc.router)


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


@app.get("/api/frontend-token", response_model=FrontendTokenResponse)
def frontend_token():
    """Genera un token de sesión temporal para el frontend.

    No requiere autenticación. El token es HMAC-firmado con un secreto
    del servidor y expira según FRONTEND_TOKEN_TTL (default 1 hora).
    """
    if not FRONTEND_TOKEN_SECRET:
        return FrontendTokenResponse(token="", expires_in=0)
    token, ttl = create_frontend_token()
    return FrontendTokenResponse(token=token, expires_in=ttl)


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    logger.warning("No se encontró el directorio frontend en %s", FRONTEND_DIR)

