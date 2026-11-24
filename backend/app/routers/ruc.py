from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.cache import build_cache
from app.config import RUC_API_KEY, RUC_CACHE_TTL
from app.dependencies import get_client_host, verify_ruc_rate_limit
from app.schemas import RucConsultaResponse, RucDetalleResponse
from app.security import require_jwt_auth
from app.services import auditoria_service, auth_service, persona_service
from app.services.ruc_service import RucService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ruc"])

ruc_cache = build_cache("ruc", maxsize=1000, ttl=RUC_CACHE_TTL)


def get_ruc_service(request: Request) -> RucService:
    svc = getattr(request.app.state, "ruc_service", None)
    if svc is None:
        svc = RucService(api_key=RUC_API_KEY)
        request.app.state.ruc_service = svc
    return svc


def _check_api_key(service: RucService) -> None:
    if not service.api_key:
        raise HTTPException(status_code=500, detail="RUC_API_KEY no configurada en .env")


def _es_usuario_real(user_payload: dict) -> bool:
    sub = user_payload.get("sub")
    return isinstance(sub, int) and sub > 0


def _consumir_consulta(user_payload: dict) -> tuple[bool, int | None]:
    """Descuenta una consulta para usuarios reales; API keys no tienen cuota."""
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
    if restantes is not None:
        response.headers["X-Consultas-Restantes"] = str(restantes)


def _reembolsar_consulta(user_payload: dict, consumida: bool) -> None:
    if consumida and _es_usuario_real(user_payload):
        auth_service.reembolsar_consulta(user_payload["sub"])


@router.get("/scraping/ruc/{dni}", response_model=RucConsultaResponse)
async def consultar_ruc_por_dni(
    dni: str,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    ruc_service: RucService = Depends(get_ruc_service),
    _rate_limit: None = Depends(verify_ruc_rate_limit),
    user_payload: dict = Depends(require_jwt_auth),
):
    if not (dni.isdigit() and len(dni) == 8):
        raise HTTPException(status_code=400, detail="DNI debe tener 8 dígitos")

    _check_api_key(ruc_service)
    consumida, restantes = _consumir_consulta(user_payload)

    cache_key = f"ruc_{dni}"
    cached = ruc_cache.get(cache_key)
    if cached is not None:
        _set_quota_header(response, restantes)
        return cached

    try:
        fila = await asyncio.to_thread(persona_service.obtener_ruc_de_persona, dni)
    except SQLAlchemyError as e:
        _reembolsar_consulta(user_payload, consumida)
        logger.exception("Error al consultar la base de datos")
        raise HTTPException(status_code=500, detail="Error interno al consultar la base de datos") from e

    if not fila or not fila["dig_ruc"]:
        result = {"tiene_ruc": False, "mensaje": "Esta persona no tiene RUC registrado"}
        ruc_cache.set(cache_key, result)
        _set_quota_header(response, restantes)
        return result

    ruc = "10" + str(fila["dni"]) + str(fila["dig_ruc"])

    try:
        data = await ruc_service.consultar(ruc)
    except HTTPException as exc:
        if exc.status_code == 404:
            result = {"tiene_ruc": False, "mensaje": "Esta persona no tiene RUC registrado"}
            ruc_cache.set(cache_key, result)
            _set_quota_header(response, restantes)
            return result
        _reembolsar_consulta(user_payload, consumida)
        raise
    except Exception:
        _reembolsar_consulta(user_payload, consumida)
        raise

    result = {
        "tiene_ruc": True,
        "dni": dni,
        "razon_social": data.get("razon_social", ""),
        "ruc": data.get("ruc", ""),
        "estado": data.get("estado", ""),
        "condicion": data.get("condicion", ""),
        "direccion": data.get("direccion", ""),
        "departamento": data.get("departamento", ""),
        "provincia": data.get("provincia", ""),
        "distrito": data.get("distrito", ""),
        "ubigeo": data.get("ubigeo", ""),
    }
    ruc_cache.set(cache_key, result)
    _set_quota_header(response, restantes)
    background_tasks.add_task(auditoria_service.registrar, get_client_host(request), "ruc", dni)
    return result


@router.get("/scraping/ruc-info/{ruc}", response_model=RucDetalleResponse)
async def consultar_ruc_detalle(
    ruc: str,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    ruc_service: RucService = Depends(get_ruc_service),
    _rate_limit: None = Depends(verify_ruc_rate_limit),
    user_payload: dict = Depends(require_jwt_auth),
):
    if not (ruc.isdigit() and len(ruc) == 11):
        raise HTTPException(status_code=400, detail="RUC debe tener 11 dígitos")

    _check_api_key(ruc_service)
    consumida, restantes = _consumir_consulta(user_payload)

    cache_key = f"rucinfo_{ruc}"
    cached = ruc_cache.get(cache_key)
    if cached is not None:
        _set_quota_header(response, restantes)
        return cached

    try:
        data = await ruc_service.consultar(ruc)
    except Exception:
        _reembolsar_consulta(user_payload, consumida)
        raise

    result = {
        "ruc": data.get("ruc", ""),
        "razon_social": data.get("razon_social", ""),
        "estado": data.get("estado", ""),
        "condicion": data.get("condicion", ""),
        "direccion": data.get("direccion", ""),
        "departamento": data.get("departamento", ""),
        "provincia": data.get("provincia", ""),
        "distrito": data.get("distrito", ""),
        "ubigeo": data.get("ubigeo", ""),
    }
    ruc_cache.set(cache_key, result)
    _set_quota_header(response, restantes)
    background_tasks.add_task(auditoria_service.registrar, get_client_host(request), "ruc_info", ruc)
    return result
