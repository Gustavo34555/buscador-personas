"""Pruebas unitarias del motor de confianza familiar.

No tocan la base de datos: validan que las coincidencias débiles (un solo
nombre de pila, nombres en otro orden o apellidos compartidos) no se
presenten como relaciones confirmadas.
"""

from datetime import date

from app.services import familia_service as fs


def _persona(**overrides):
    base = {
        "dni": "43761388",
        "nombres": "MILAGROS MARIA",
        "ap_pat": "CHIROQUE",
        "ap_mat": "JAPAY",
        "padre": "MANUEL JESUS",
        "madre": "LEONCIA MARINA",
        "fecha_nac": date(1985, 10, 17),
        "sexo": "2",
        "ubigeo_nac": "150101",
        "ubigeo_dir": "LIMA-LIMA-LIMA",
        "direccion": "AV. SIEMPRE VIVA 123",
    }
    base.update(overrides)
    return base


def test_progenitor_con_un_solo_nombre_es_evidencia_debil():
    puntos, conflicto, evidencia = fs._compatibilidad_campos_progenitor("MANUEL JESUS", "MANUEL")
    assert puntos == 10
    assert conflicto is False
    assert evidencia[0]["codigo"] == "progenitor_primer_nombre"


def test_dos_coincidencias_debiles_no_confirman_hermano_completo():
    persona = _persona()
    candidato = {
        "dni": "41833027",
        "nombres": "LUIS ENRIQUE",
        "ap_pat": "CHIROQUE",
        "ap_mat": "JAPAY",
        "padre": "MANUEL",
        "madre": "LEONCIA",
        "fecha_nac": date(1982, 12, 23),
        "sexo": "1",
        "ubigeo_nac": "150101",
        "ubigeo_dir": "LIMA-LIMA-LIMA",
        "direccion": "AV. SIEMPRE VIVA 123",
    }
    puntos, _, tipo, conflicto = fs._puntuar_hermano(candidato, persona, persona["padre"], persona["madre"])
    assert conflicto is False
    assert tipo == "hermano_probable"
    assert puntos < 50


def test_medio_hermano_solo_por_primer_nombre_sin_contexto_se_descarta():
    persona = _persona()
    candidato = {
        "dni": "43383379",
        "nombres": "JAVIER",
        "ap_pat": "CHIROQUE",
        "ap_mat": "MORE",
        "padre": "MANUEL",
        "madre": "MARIA",
        "fecha_nac": date(1984, 1, 1),
        "sexo": "1",
        "ubigeo_nac": "080101",
        "ubigeo_dir": "CUSCO-CUSCO-CUSCO",
        "direccion": "CALLE OTRA 456",
    }
    _, _, tipo, conflicto = fs._puntuar_hermano(candidato, persona, persona["padre"], persona["madre"])
    assert conflicto is True
    assert tipo == "debil_sin_contexto"


def test_medio_hermano_debil_con_misma_provincia_queda_como_probable():
    persona = _persona()
    candidato = {
        "dni": "43383380",
        "nombres": "JAVIER",
        "ap_pat": "CHIROQUE",
        "ap_mat": "MORE",
        "padre": "MANUEL",
        "madre": "MARIA",
        "fecha_nac": date(1984, 1, 1),
        "sexo": "1",
        # Misma provincia (1501) pero distrito distinto.
        "ubigeo_nac": "150102",
        "ubigeo_dir": "LIMA-LIMA-SAN MARTIN DE PORRES",
        "direccion": "CALLE OTRA 456",
    }
    puntos, _, tipo, conflicto = fs._puntuar_hermano(candidato, persona, persona["padre"], persona["madre"])
    assert conflicto is False
    assert tipo == "hermano_probable"
    assert puntos < 50


def test_hijo_con_nombre_exacto_se_confirma():
    persona = _persona()
    candidato = {
        "dni": "61038157",
        "nombres": "CAMILO ANDRES",
        "ap_pat": "LLAMPAZO",
        "ap_mat": "CHIROQUE",
        "padre": "GILMARS CAMILO",
        "madre": "MILAGROS MARIA",
        "fecha_nac": date(2007, 3, 12),
        "sexo": "1",
        "ubigeo_nac": "150101",
        "ubigeo_dir": "LIMA-LIMA-LIMA",
        "direccion": "AV. SIEMPRE VIVA 123",
    }
    puntos, _, conflicto, probable = fs._puntuar_hijo(candidato, persona, "madre", "ap_mat")
    assert conflicto is False
    assert probable is False
    assert puntos >= 60


def test_hijo_con_nombres_en_otro_orden_sin_contexto_se_descarta():
    persona = _persona()
    candidato = {
        "dni": "60669141",
        "nombres": "LEYSI MABEL",
        "ap_pat": "VILCHEZ",
        "ap_mat": "CHIROQUE",
        "padre": "HUMBERTO",
        "madre": "MARIA MILAGROS",
        "fecha_nac": date(2008, 9, 27),
        "sexo": "2",
        "ubigeo_nac": "080101",
        "ubigeo_dir": "CUSCO-CUSCO-CUSCO",
        "direccion": "CALLE OTRA 456",
    }
    _, _, conflicto, _ = fs._puntuar_hijo(candidato, persona, "madre", "ap_mat")
    assert conflicto is True


def test_hijo_con_nombres_en_otro_orden_y_misma_zona_queda_probable():
    persona = _persona()
    candidato = {
        "dni": "60669142",
        "nombres": "LEYSI MABEL",
        "ap_pat": "VILCHEZ",
        "ap_mat": "CHIROQUE",
        "padre": "HUMBERTO",
        "madre": "MARIA MILAGROS",
        "fecha_nac": date(2008, 9, 27),
        "sexo": "2",
        "ubigeo_nac": "150102",
        "ubigeo_dir": "LIMA-LIMA-SAN MARTIN DE PORRES",
        "direccion": "CALLE OTRA 456",
    }
    puntos, _, conflicto, probable = fs._puntuar_hijo(candidato, persona, "madre", "ap_mat")
    assert conflicto is False
    assert probable is True
    assert puntos < 50


def test_hermanos_con_progenitores_completos_se_confirman():
    """Dos progenitores con nombre completo sí sostienen la confianza alta."""
    persona = _persona()
    candidato = {
        "dni": "41833028",
        "nombres": "LUIS ENRIQUE",
        "ap_pat": "CHIROQUE",
        "ap_mat": "JAPAY",
        "padre": "MANUEL JESUS",
        "madre": "LEONCIA MARINA",
        "fecha_nac": date(1982, 12, 23),
        "sexo": "1",
        "ubigeo_nac": "150101",
        "ubigeo_dir": "LIMA-LIMA-LIMA",
        "direccion": "AV. SIEMPRE VIVA 123",
    }
    puntos, _, tipo, conflicto = fs._puntuar_hermano(candidato, persona, persona["padre"], persona["madre"])
    assert conflicto is False
    assert tipo == "hermano_completo"
    assert puntos >= 60


def test_medio_hermano_requiere_contexto_aun_con_nombre_fuerte():
    """Nombre exacto sin contexto se descarta; con misma provincia se confirma."""
    persona = _persona()
    base = {
        "dni": "43383381",
        "nombres": "JAVIER",
        "ap_pat": "CHIROQUE",
        "ap_mat": "MORE",
        "padre": "MANUEL JESUS",
        "madre": "OTRA",
        "fecha_nac": date(1984, 1, 1),
        "sexo": "1",
    }

    sin_contexto = {**base, "ubigeo_nac": "080101", "ubigeo_dir": "CUSCO-CUSCO-CUSCO", "direccion": "CALLE OTRA 456"}
    _, _, tipo, conflicto = fs._puntuar_hermano(sin_contexto, persona, persona["padre"], persona["madre"])
    assert conflicto is True
    assert tipo == "debil_sin_contexto"

    con_contexto = {
        **base,
        "ubigeo_nac": "150101",
        "ubigeo_dir": "LIMA-LIMA-LIMA",
        "direccion": "CALLE OTRA 456",
    }
    puntos, _, tipo, conflicto = fs._puntuar_hermano(con_contexto, persona, persona["padre"], persona["madre"])
    assert conflicto is False
    assert tipo == "medio_hermano_paterno"
    assert puntos >= 40


def test_evidencia_documental_suma_apoyo_limitado():
    fechas = {
        "fch_inscripcion": "2000-01-01",
        "fch_emision": "2010-01-01",
        "fch_caducidad": "2020-01-01",
    }
    puntos, evidencias = fs._evidencia_documental(fechas, fechas)
    assert puntos == 6
    assert {e["codigo"] for e in evidencias} == {
        "misma_inscripcion",
        "misma_emision",
        "misma_caducidad",
    }


def test_numero_de_domicilio_solo_penaliza_calles_similares():
    referencia = {"direccion": "AV. SIEMPRE VIVA 123"}
    misma_calle = {"direccion": "AV. SIEMPRE VIVA 456"}
    calle_distinta = {"direccion": "CALLE OTRA 456"}

    puntos, evidencias = fs._evidencia_direccion(misma_calle, referencia)
    assert puntos == -5
    assert evidencias[0]["codigo"] == "numero_direccion_distinto"

    puntos, evidencias = fs._evidencia_direccion(calle_distinta, referencia)
    assert puntos == 0
    assert evidencias == []


def test_umbrales_de_confianza_son_estrictos():
    """Solo evidencia muy sólida debe figurar como confianza alta."""
    from app import config

    assert config.FAMILIA_UMBRAL_ALTA >= 70
    assert config.FAMILIA_UMBRAL_MEDIA >= 50


def test_relaciones_probables_ocultas_por_defecto():
    """Solo se muestran indicios si el operador lo habilita explícitamente."""
    from app import config

    assert config.FAMILIA_INCLUIR_PROBABLES is False
