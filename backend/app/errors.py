"""Errores de dominio compartidos entre servicios y routers."""


class QueryExecutionError(RuntimeError):
    """La base de datos falló o canceló una consulta.

    No debe confundirse con "la consulta terminó sin filas": cuando se lanza,
    la petición debe devolver 503/504 y reembolsar la cuota consumida.
    """
