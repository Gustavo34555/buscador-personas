class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return dict(self._rows[0]) if self._rows else None

    def all(self):
        return [dict(r) for r in self._rows]


class FakeConn:
    def __init__(self, rows=None):
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        return FakeResult(self.rows)

    def commit(self) -> None:
        pass


class FakeEngine:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.connect_count = 0

    def connect(self):
        self.connect_count += 1
        return FakeConn(self.rows)


PERSONA_FILA = {
    "dni": "12345678",
    "ap_pat": "Garcia",
    "ap_mat": "Perez",
    "nombres": "Juan Carlos",
    "padre": None,
    "madre": None,
    "fecha_nac": "1990-01-15",
    "fch_emision": None,
    "fch_inscripcion": None,
    "fch_caducidad": None,
    "direccion": "Av. Lima 123",
    "ubigeo_nac": "150101",
    "ubigeo_dir": "150101",
    "sexo": "Masculino",
    "est_civil": "Soltero",
    "edad_anios": 36,
    "edad_meses": 6,
    "edad_dias": 23,
    "edad_texto": "36 años, 6 meses, 23 días",
}
