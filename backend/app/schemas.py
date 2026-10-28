"""Esquemas Pydantic de respuesta para la API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


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


class EvidenciaArbol(BaseModel):
    """Evidencia que sustenta una relación familiar."""

    codigo: str
    descripcion: str
    puntos: int


class CandidatoArbol(BaseModel):
    """Candidato alternativo para una relación familiar."""

    dni: str | None = None
    nombres: str | None = None
    ap_pat: str | None = None
    ap_mat: str | None = None
    fecha_nac: date | str | None = None
    sexo: str | None = None
    confianza: int = 0
    nivel_confianza: str = "baja"
    evidencia: list[EvidenciaArbol] = Field(default_factory=list)


class ArbolNodo(BaseModel):
    """Nodo del árbol genealógico con confianza y evidencia."""

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
    direccion: str | None = None
    ubigeo_nac: str | None = None
    ubigeo_dir: str | None = None
    encontrado: bool = False
    confianza: int | None = None
    nivel_confianza: str | None = None
    evidencia: list[EvidenciaArbol] = Field(default_factory=list)
    candidatos: list[CandidatoArbol] = Field(default_factory=list)
    tipo_relacion: str | None = None

    model_config = {"from_attributes": True}


class ArbolMeta(BaseModel):
    """Metadatos del proceso de construcción del árbol."""

    version: str
    limite_por_relacion: int
    umbral_alta: int
    umbral_media: int
    candidatos_analizados_por_relacion: int
    advertencias: list[str] = Field(default_factory=list)


class ArbolResponse(BaseModel):
    """Respuesta completa del árbol genealógico."""

    persona: ArbolNodo
    padre: ArbolNodo | None = None
    madre: ArbolNodo | None = None
    abuelo_paterno: ArbolNodo | None = None
    abuela_paterna: ArbolNodo | None = None
    abuelo_materno: ArbolNodo | None = None
    abuela_materna: ArbolNodo | None = None
    hermanos: list[ArbolNodo] = Field(default_factory=list)
    hijos: list[ArbolNodo] = Field(default_factory=list)
    meta: ArbolMeta | None = None


class FichaReferenciaC4Response(BaseModel):
    """Ficha de referencia generada a partir de los datos del padrón.

    No reproduce un certificado oficial: solo incluye un código interno de
    referencia y los datos consultados. No hay MRZ, firma digital ni URL de
    verificación porque el documento no tiene validez legal.
    """

    codigo_referencia: str
    fecha_generacion: str
    persona: PersonaResponse
    es_oficial: bool = False
    aviso: str | None = None


# ── Auth & Admin Schemas ──────────────────────────────────────


class LoginRequest(BaseModel):
    """Datos de login."""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    """Respuesta al login exitoso."""

    token: str
    username: str
    rol: str
    consultas_restantes: int
    expires_in: int | None = None


class MeResponse(BaseModel):
    """Datos del usuario autenticado."""

    id: int
    username: str
    rol: str
    consultas_max: int
    consultas_usadas: int
    consultas_restantes: int


class UsuarioResponse(BaseModel):
    """Datos de un usuario (para el panel admin)."""

    id: int
    username: str
    rol: str
    consultas_max: int
    consultas_usadas: int
    activo: bool
    created_at: str | None = None

    model_config = {"from_attributes": True}


class CrearUsuarioRequest(BaseModel):
    """Datos para crear un nuevo usuario."""

    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=72)
    consultas_max: int = Field(default=100, ge=0, le=1_000_000)


class ActualizarUsuarioRequest(BaseModel):
    """Datos para actualizar un usuario existente."""

    consultas_max: int | None = Field(default=None, ge=0, le=1_000_000)
    activo: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
