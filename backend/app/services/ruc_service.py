import asyncio
import logging

import httpx
from fastapi import HTTPException

from app.config import RUC_API_BASE, RUC_API_KEY

logger = logging.getLogger(__name__)


class RucService:
    """Cliente de la API de peruapi.com para consultas RUC con reintentos."""

    def __init__(self, api_key: str = RUC_API_KEY):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def consultar(self, ruc: str, max_retries: int = 2) -> dict:
        if not self.api_key:
            raise HTTPException(
                status_code=500,
                detail="RUC_API_KEY no configurada en .env",
            )

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                res = await self.client.get(
                    f"{RUC_API_BASE}/ruc/{ruc}",
                    headers={"X-API-KEY": self.api_key},
                )
                if res.status_code == 404:
                    raise HTTPException(
                        status_code=404,
                        detail="RUC no encontrado en el padrón SUNAT",
                    )
                if res.status_code == 401:
                    try:
                        err_body = res.json()
                        api_msg = err_body.get("mensaje") or err_body.get("message")
                    except Exception:
                        api_msg = None
                    detail = api_msg or "RUC_API_KEY inválida o no configurada. Regístrate gratis en https://peruapi.com/registro"
                    raise HTTPException(
                        status_code=500,
                        detail=detail,
                    )
                if res.status_code == 429:
                    raise HTTPException(
                        status_code=429,
                        detail="Límite de consultas RUC alcanzado. Intenta más tarde.",
                    )
                if res.status_code >= 500 and attempt < max_retries:
                    logger.warning(
                        "Error %s de API RUC en intento %d/%d, reintentando...",
                        res.status_code,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue
                if res.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Error al consultar la API de RUC (HTTP {res.status_code})",
                    )
                return res.json()
            except httpx.RequestError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(
                        "Fallo de red en intento %d/%d con API RUC: %s. Reintentando...",
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue

        raise HTTPException(
            status_code=502,
            detail="No se pudo conectar con la API de RUC tras varios intentos",
        ) from last_error
