import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.cache import TTLCache
from app.config import RUC_API_KEY, RUC_CACHE_TTL
from app.dependencies import get_client_host, verify_ruc_rate_limit
from app.schemas import RucConsultaResponse, RucDetalleResponse
from app.security import require_api_key
from app.services import auditoria_service, persona_service
from app.services.ruc_service import RucService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ruc"])

ruc_cache = TTLCache(maxsize=1000, ttl=RUC_CACHE_TTL)


def get_ruc_service(request: Request) -> RucService:
    svc = getattr(request.app.state, "ruc_service", None)
    if svc is None:
        svc = RucService(api_key=RUC_API_KEY)
        request.app.state.ruc_service = svc
    return svc


def _check_api_key(service: RucService) -> None:
    if not service.api_key:
        raise HTTPException(status_code=500, detail="RUC_API_KEY no configurada en .env")


@router.get("/scraping/ruc/{dni}", response_model=RucConsultaResponse)
async def consultar_ruc_por_dni(
    dni: str,
    request: Request,
    background_tasks: BackgroundTasks,
    ruc_service: RucService = Depends(get_ruc_service),
    _rate_limit: None = Depends(verify_ruc_rate_limit),
    _auth: None = Depends(require_api_key),
):
    if not (dni.isdigit() and len(dni) == 8):
        raise HTTPException(status_code=400, detail="DNI debe tener 8 dígitos")

    _check_api_key(ruc_service)

    cache_key = f"ruc_{dni}"
    cached = ruc_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        fila = await asyncio.to_thread(persona_service.obtener_ruc_de_persona, dni)
    except SQLAlchemyError as e:
        logger.exception("Error al consultar la base de datos")
        raise HTTPException(status_code=500, detail="Error interno al consultar la base de datos") from e

    if not fila or not fila["dig_ruc"]:
        return {"tiene_ruc": False, "mensaje": "Esta persona no tiene RUC registrado"}

    ruc = "10" + str(fila["dni"]) + str(fila["dig_ruc"])

    try:
        data = await ruc_service.consultar(ruc)
    except HTTPException as exc:
        if exc.status_code == 404:
            return {"tiene_ruc": False, "mensaje": "Esta persona no tiene RUC registrado"}
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
    background_tasks.add_task(auditoria_service.registrar, get_client_host(request), "ruc", dni)
    return result


@router.get("/scraping/ruc-info/{ruc}", response_model=RucDetalleResponse)
async def consultar_ruc_detalle(
    ruc: str,
    request: Request,
    ruc_service: RucService = Depends(get_ruc_service),
    _rate_limit: None = Depends(verify_ruc_rate_limit),
    _auth: None = Depends(require_api_key),
):
    if not (ruc.isdigit() and len(ruc) == 11):
        raise HTTPException(status_code=400, detail="RUC debe tener 11 dígitos")

    _check_api_key(ruc_service)

    cache_key = f"rucinfo_{ruc}"
    cached = ruc_cache.get(cache_key)
    if cached is not None:
        return cached

    data = await ruc_service.consultar(ruc)

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
    return result
