import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.cache import TTLCache
from app.config import BUSCAR_CACHE_TTL, DNI_CACHE_TTL
from app.dependencies import get_client_host, verify_search_rate_limit
from app.schemas import PersonaBusquedaItem, PersonaResponse
from app.security import require_api_key
from app.services import auditoria_service, persona_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["personas"])

dni_cache = TTLCache(maxsize=1000, ttl=DNI_CACHE_TTL)
buscar_cache = TTLCache(maxsize=500, ttl=BUSCAR_CACHE_TTL)


@router.get("/persona/{dni}", response_model=PersonaResponse)
async def obtener_persona(
    dni: str,
    request: Request,
    background_tasks: BackgroundTasks,
    _rate_limit: None = Depends(verify_search_rate_limit),
    _auth: None = Depends(require_api_key),
):
    if not (dni.isdigit() and len(dni) == 8):
        raise HTTPException(status_code=400, detail="DNI debe tener 8 dígitos")

    cached = dni_cache.get(dni)
    if cached is not None:
        return cached

    try:
        fila = await asyncio.to_thread(persona_service.obtener_por_dni, dni)
    except SQLAlchemyError as e:
        logger.exception("Error al consultar la base de datos")
        raise HTTPException(status_code=500, detail="Error interno al consultar la base de datos") from e

    if not fila:
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    result = dict(fila)
    dni_cache.set(dni, result)
    background_tasks.add_task(auditoria_service.registrar, get_client_host(request), "persona", dni)
    return result


@router.get("/buscar", response_model=list[PersonaBusquedaItem])
async def buscar_personas(
    request: Request,
    background_tasks: BackgroundTasks,
    q: str = Query(..., min_length=2, description="Nombre o apellido a buscar"),
    limit: int = Query(20, ge=1, le=200, description="Máximo de resultados"),
    _rate_limit: None = Depends(verify_search_rate_limit),
    _auth: None = Depends(require_api_key),
):
    q = " ".join(q.strip().split())
    if not q:
        return []

    if len(q) < 3:
        raise HTTPException(
            status_code=400,
            detail="Búsqueda muy corta: mínimo 3 caracteres",
        )

    cache_key = f"{q}:{limit}"
    cached = buscar_cache.get(cache_key)
    if cached is not None:
        return cached

    q_lower = q.lower()
    q_prefix = q_lower + "%"

    try:
        filas = await asyncio.to_thread(
            persona_service.buscar_personas,
            q=q,
            q_lower=q_lower,
            q_prefix=q_prefix,
            dni_prefix=f"{q}%",
            num_words=len(q_lower.split()),
            limit=limit,
        )
    except SQLAlchemyError as e:
        logger.exception("Error al consultar la base de datos")
        raise HTTPException(status_code=500, detail="Error interno al consultar la base de datos") from e

    result = [dict(fila) for fila in filas]
    buscar_cache.set(cache_key, result)
    background_tasks.add_task(auditoria_service.registrar, get_client_host(request), "buscar", q)
    return result
