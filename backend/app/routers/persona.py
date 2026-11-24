from __future__ import annotations

import asyncio
import logging
import unicodedata

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.cache import build_cache
from app.config import (
    ARBOL_CACHE_TTL,
    BUSCAR_CACHE_TTL,
    DNI_CACHE_TTL,
    FAMILIA_LIMITE_DEFAULT,
    FAMILIA_LIMITE_MAX,
    NEGATIVE_CACHE_TTL,
)
from app.dependencies import get_client_host, verify_search_rate_limit
from app.errors import QueryExecutionError
from app.schemas import ArbolResponse, PersonaBusquedaItem, PersonaResponse
from app.security import require_jwt_auth
from app.services import auditoria_service, auth_service, persona_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["personas"])

dni_cache = build_cache("dni", maxsize=1000, ttl=DNI_CACHE_TTL)
buscar_cache = build_cache("buscar", maxsize=500, ttl=BUSCAR_CACHE_TTL)
arbol_cache = build_cache("arbol", maxsize=500, ttl=ARBOL_CACHE_TTL)
# Evita repetir consultas a la base para DNIs inexistentes (también frena
# intentos de enumeración). Es independiente de la cuota: un 404 se reembolsa.
dni_negative_cache = build_cache("dni_negative", maxsize=2000, ttl=NEGATIVE_CACHE_TTL)
arbol_negative_cache = build_cache("arbol_negative", maxsize=2000, ttl=NEGATIVE_CACHE_TTL)

# Prefijo de versión: un deploy con otro scoring no debe servir respuestas viejas.
CACHE_VERSION = "v3"


def _escape_like(text: str) -> str:
    """Escapa comodines SQL LIKE para no alterar el patrón ni el score."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fila_dni(dni: str) -> dict | None:
    fila = persona_service.obtener_por_dni(dni)
    return dict(fila) if fila is not None else None


def _dict_fila(fila) -> dict:
    return dict(fila)


def _upstream_timeout(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=504,
        detail="La consulta tardó demasiado; intenta de nuevo",
        headers={"Retry-After": "5"},
    )


def _query_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Servicio de consulta no disponible; intenta de nuevo en unos segundos",
        headers={"Retry-After": "5"},
    )


def _normalize_text(text: str) -> str:
    """Remueve diacríticos y acentos para búsqueda insensible a tildes."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _es_usuario_real(user_payload: dict) -> bool:
    """Los API keys y el modo abierto no consumen la cuota de un usuario."""
    sub = user_payload.get("sub")
    return isinstance(sub, int) and sub > 0


def _consumir_consulta(user_payload: dict) -> tuple[bool, int | None]:
    """Descuenta una consulta de forma atómica.

    Retorna ``(consumida, restantes)``. ``consumida`` permite reembolsar la
    consulta cuando la operación no llega a entregar datos. Los
    administradores, las API keys y el modo abierto no tienen cuota, por lo
    que ``restantes`` es ``None``.
    """
    if user_payload.get("rol") == "admin" or not _es_usuario_real(user_payload):
        return False, None

    restantes = auth_service.consumir_consulta(user_payload["sub"])
    if restantes is None:
        raise HTTPException(
            status_code=403,
            detail="Sin consultas disponibles. Contacta al administrador para obtener más.",
        )
    return True, restantes


def _set_quota_header(response: Response, restantes: int | None) -> None:
    """Expone el saldo exacto para que el frontend no haga otra petición."""
    if restantes is not None:
        response.headers["X-Consultas-Restantes"] = str(restantes)


def _reembolsar_consulta(user_payload: dict, consumida: bool) -> None:
    if consumida and _es_usuario_real(user_payload):
        auth_service.reembolsar_consulta(user_payload["sub"])


@router.get("/persona/{dni}", response_model=PersonaResponse)
async def obtener_persona(
    dni: str,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    _rate_limit: None = Depends(verify_search_rate_limit),
    user_payload: dict = Depends(require_jwt_auth),
):
    if not (dni.isdigit() and len(dni) == 8):
        raise HTTPException(status_code=400, detail="DNI debe tener 8 dígitos")

    consumida, restantes = _consumir_consulta(user_payload)

    if dni_negative_cache.get(dni) is not None:
        _reembolsar_consulta(user_payload, consumida)
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    cached = dni_cache.get(dni)
    if cached is not None:
        _set_quota_header(response, restantes)
        return cached

    try:
        fila = await asyncio.to_thread(dni_cache.get_or_set, dni, lambda: _fila_dni(dni))
    except asyncio.TimeoutError as e:
        _reembolsar_consulta(user_payload, consumida)
        raise _upstream_timeout(e) from e
    except QueryExecutionError as e:
        _reembolsar_consulta(user_payload, consumida)
        raise _query_unavailable(e) from e
    except SQLAlchemyError as e:
        _reembolsar_consulta(user_payload, consumida)
        logger.error("Error de base de datos: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error interno al consultar la base de datos") from e

    if not fila:
        dni_negative_cache.set(dni, True)
        _reembolsar_consulta(user_payload, consumida)
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    result = dict(fila)
    dni_negative_cache.delete(dni)
    dni_cache.set(dni, result)
    _set_quota_header(response, restantes)
    background_tasks.add_task(auditoria_service.registrar, get_client_host(request), "persona", dni)
    return result


@router.get("/buscar", response_model=list[PersonaBusquedaItem])
async def buscar_personas(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    q: str = Query(..., min_length=2, max_length=100, description="Nombre o apellido a buscar"),
    limit: int = Query(20, ge=1, le=200, description="Máximo de resultados"),
    _rate_limit: None = Depends(verify_search_rate_limit),
    user_payload: dict = Depends(require_jwt_auth),
):
    q = " ".join(q.strip().split())
    if not q:
        return []

    if len(q) < 3:
        raise HTTPException(
            status_code=400,
            detail="Búsqueda muy corta: mínimo 3 caracteres",
        )

    # La clave usa el texto normalizado: "García" y "Garcia" comparten caché.
    q_normalized = _normalize_text(q)
    q_lower = q_normalized.lower()
    cache_key = f"{CACHE_VERSION}:{q_lower}:{limit}"

    consumida, restantes = _consumir_consulta(user_payload)

    cached = buscar_cache.get(cache_key)
    if cached is not None:
        _set_quota_header(response, restantes)
        return cached

    q_prefix = _escape_like(q_lower) + "%"

    words = q_lower.split()
    w1 = words[0] if len(words) >= 1 else ""
    w2 = words[1] if len(words) >= 2 else ""
    w3 = words[2] if len(words) >= 3 else ""
    w4 = words[3] if len(words) >= 4 else ""

    try:
        filas = await asyncio.wait_for(
            asyncio.to_thread(
                buscar_cache.get_or_set,
                cache_key,
                lambda: [
                    _dict_fila(f)
                    for f in persona_service.buscar_personas(
                        q=q_normalized,
                        q_lower=q_lower,
                        q_prefix=q_prefix,
                        dni_prefix=_escape_like(q_lower) + "%",
                        num_words=len(words),
                        limit=limit,
                        w1=w1,
                        w2=w2,
                        w3=w3,
                        w4=w4,
                    )
                ],
            ),
            timeout=25,
        )
    except asyncio.TimeoutError as e:
        _reembolsar_consulta(user_payload, consumida)
        raise _upstream_timeout(e) from e
    except QueryExecutionError as e:
        _reembolsar_consulta(user_payload, consumida)
        raise _query_unavailable(e) from e
    except SQLAlchemyError as e:
        _reembolsar_consulta(user_payload, consumida)
        logger.error("Error de base de datos: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error interno al consultar la base de datos") from e

    result = [dict(fila) for fila in filas]
    buscar_cache.set(cache_key, result)
    _set_quota_header(response, restantes)
    background_tasks.add_task(auditoria_service.registrar, get_client_host(request), "buscar", q)
    return result


@router.get("/persona/{dni}/arbol", response_model=ArbolResponse)
async def arbol_genealogico(
    dni: str,
    response: Response,
    limite: int = Query(
        default=FAMILIA_LIMITE_DEFAULT,
        ge=1,
        le=FAMILIA_LIMITE_MAX,
        description="Máximo de hermanos e hijos devueltos por relación",
    ),
    _rate_limit: None = Depends(verify_search_rate_limit),
    user_payload: dict = Depends(require_jwt_auth),
):
    if not (dni.isdigit() and len(dni) == 8):
        raise HTTPException(status_code=400, detail="DNI debe tener 8 dígitos")

    consumida, restantes = _consumir_consulta(user_payload)

    if arbol_negative_cache.get(dni) is not None:
        _reembolsar_consulta(user_payload, consumida)
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    cache_key = f"{CACHE_VERSION}:{dni}:{limite}"
    cached = arbol_cache.get(cache_key)
    if cached is not None:
        _set_quota_header(response, restantes)
        return cached

    try:
        arbol = await asyncio.wait_for(
            asyncio.to_thread(arbol_cache.get_or_set, cache_key, lambda: persona_service.construir_arbol(dni, limite)),
            timeout=25,
        )
    except asyncio.TimeoutError as e:
        _reembolsar_consulta(user_payload, consumida)
        raise _upstream_timeout(e) from e
    except QueryExecutionError as e:
        _reembolsar_consulta(user_payload, consumida)
        raise _query_unavailable(e) from e
    except SQLAlchemyError as e:
        _reembolsar_consulta(user_payload, consumida)
        logger.error("Error de base de datos al construir el árbol: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error interno al consultar la base de datos") from e

    if not arbol:
        arbol_negative_cache.set(dni, True)
        _reembolsar_consulta(user_payload, consumida)
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    arbol_cache.set(cache_key, arbol)
    _set_quota_header(response, restantes)
    return arbol
