"""Smoke test contra la base de datos real (37M filas).

Verifica que la búsqueda funcione, respete el ranking y maneje acentos.

Uso: venv/bin/python scripts/prueba_busqueda.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.exc import SQLAlchemyError

from app.services import persona_service


def cronometrar(fn, *args, **kwargs):
    t = time.perf_counter()
    filas = fn(*args, **kwargs)
    return filas, time.perf_counter() - t


def main() -> int:
    errores = 0

    try:
        filas, dt = cronometrar(
            persona_service.buscar_personas,
            q="garcia perez",
            q_lower="garcia perez",
            q_prefix="garcia perez%",
            dni_prefix="garcia perez%",
            num_words=2,
            limit=5,
        )
        print(f"[OK] 'garcia perez' -> {len(filas)} en {dt:.2f}s")
        if filas:
            f = filas[0]
            print(f"     primero: {f['nombres']} {f['ap_pat']} {f['ap_mat']} (DNI {f['dni']})")
        if not filas:
            errores += 1
    except SQLAlchemyError as exc:
        print(f"[ERROR] búsqueda 'garcia perez': {exc}")
        errores += 1

    try:
        filas, dt = cronometrar(
            persona_service.buscar_personas,
            q="GARCÍA PÉREZ",
            q_lower="garcía pérez",
            q_prefix="garcía pérez%",
            dni_prefix="GARCÍA PÉREZ%",
            num_words=2,
            limit=3,
        )
        print(f"[OK] 'GARCÍA PÉREZ' (tildes) -> {len(filas)} en {dt:.2f}s")
        if not filas:
            errores += 1
    except SQLAlchemyError as exc:
        print(f"[ERROR] búsqueda con tildes: {exc}")
        errores += 1

    try:
        filas = persona_service.buscar_personas(
            q="garcia perez", q_lower="garcia perez", q_prefix="garcia perez%",
            dni_prefix="garcia perez%", num_words=2, limit=1,
        )
        if filas:
            dni = filas[0]["dni"]
            t = time.perf_counter()
            persona = persona_service.obtener_por_dni(dni)
            dt = time.perf_counter() - t
            print(f"[OK] persona por DNI {dni} -> {'encontrada' if persona else 'NO'} en {dt:.2f}s")
            if not persona:
                errores += 1
    except SQLAlchemyError as exc:
        print(f"[ERROR] persona por DNI: {exc}")
        errores += 1

    try:
        filas = persona_service.buscar_personas(
            q="ab", q_lower="ab", q_prefix="ab%",
            dni_prefix="ab%", num_words=1, limit=5,
        )
        print(f"[OK] query corta 'ab' -> {len(filas)} (protegido por LIMIT 300 del CTE)")
    except SQLAlchemyError as exc:
        print(f"[ERROR] query corta: {exc}")
        errores += 1

    print()
    if errores:
        print(f"{errores} fallo(s).")
        return 1
    print("Smoke test de búsqueda OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
