"""Esquemas Pydantic de respuesta para la API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class PersonaResponse(BaseModel):
    """Datos completos de una persona por DNI."""

    dni: str
    ap_pat: str | None = None
    ap_mat: str | None = None
    nombres: str | None = None
    padre: str | None = None
    madre: str | None = None
    fecha_nac: date | str | None = None
    fch_emision: date | str | None = None
    fch_inscripcion: date | str | None = None
    fch_caducidad: date | str | None = None
    direccion: str | None = None
    ubigeo_nac: str | None = None
    ubigeo_dir: str | None = None
    sexo: str | None = None
    est_civil: str | None = None
    edad_anios: int | None = None
    edad_meses: int | None = None
    edad_dias: int | None = None
    edad_texto: str | None = None

    model_config = {"from_attributes": True}


class PersonaBusquedaItem(PersonaResponse):
    """Resultado de búsqueda por nombre (incluye dígito RUC y ranking)."""

    dig_ruc: str | int | None = None
    rank_score: float | None = None


class RucConsultaResponse(BaseModel):
    """Resultado de consulta RUC por DNI."""

    tiene_ruc: bool
    dni: str | None = None
    razon_social: str | None = None
    ruc: str | None = None
    estado: str | None = None
    condicion: str | None = None
    direccion: str | None = None
    departamento: str | None = None
    provincia: str | None = None
    distrito: str | None = None
    ubigeo: str | None = None
    mensaje: str | None = None


class RucDetalleResponse(BaseModel):
    """Detalle de un RUC."""

    ruc: str | None = None
    razon_social: str | None = None
    estado: str | None = None
    condicion: str | None = None
    direccion: str | None = None
    departamento: str | None = None
    provincia: str | None = None
    distrito: str | None = None
    ubigeo: str | None = None


class StatusResponse(BaseModel):
    """Estado de la API."""

    mensaje: str
    database: str = "ok"


class FrontendTokenResponse(BaseModel):
    """Token de sesión para el frontend."""

    token: str
    expires_in: int


class ArbolNodo(BaseModel):
    """Nodo básico del árbol genealógico."""

    dni: str | None = None
    nombres: str | None = None
    ap_pat: str | None = None
    ap_mat: str | None = None
    sexo: str | None = None
    edad_anios: int | None = None
    fecha_nac: date | str | None = None
    est_civil: str | None = None
    padre: str | None = None
    madre: str | None = None
    encontrado: bool = False

    model_config = {"from_attributes": True}


class ArbolResponse(BaseModel):
    """Respuesta completa del árbol genealógico."""

    persona: ArbolNodo
    padre: ArbolNodo | None = None
    madre: ArbolNodo | None = None
    abuelo_paterno: ArbolNodo | None = None
    abuela_paterna: ArbolNodo | None = None
    abuelo_materno: ArbolNodo | None = None
    abuela_materna: ArbolNodo | None = None
    hermanos: list[ArbolNodo] = []
    hijos: list[ArbolNodo] = []

