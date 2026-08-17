"""Verifica que la base de datos tenga lo que la API necesita:
extensiones (pg_trgm, unaccent), función immutable_unaccent e índices de personas.

Uso: venv/bin/python scripts/verificar_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text

from app.config import DATABASE_URL

EXTENSIONES = {"pg_trgm", "unaccent"}

INDICES_REQUERIDOS = {
    "search_vector": "GIN",
    "nombre_completo": "trgm",
    "dni": "btree/único",
}


def main() -> int:
    engine = create_engine(DATABASE_URL, future=True)
    errores = 0

    with engine.connect() as conn:
        ext = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT extname FROM pg_extension "
                    "WHERE extname IN ('pg_trgm', 'unaccent')"
                )
            )
        }
        faltantes = EXTENSIONES - ext
        print(f"[{'OK' if not faltantes else 'FALTA'}] extensiones: {sorted(ext) or 'ninguna'}")
        errores += len(faltantes)

        funcs = conn.execute(
            text(
                "SELECT provolatile FROM pg_proc WHERE proname = 'immutable_unaccent'"
            )
        ).all()
        if funcs and funcs[0][0] == "i":
            print("[OK] función immutable_unaccent (volatile=immutable)")
        else:
            print(
                "[FALTA] función immutable_unaccent NO existe o no es INMUTABLE. "
                "Crea: CREATE FUNCTION immutable_unaccent(text) RETURNS text "
                "AS 'SELECT public.unaccent(public.unaccent(text))' LANGUAGE sql IMMUTABLE STRICT;"
            )
            errores += 1

        try:
            indices = conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'personas' ORDER BY indexname"
                )
            ).all()
        except Exception as exc:
            print(f"[ERROR] tabla 'personas' no accesible: {exc}")
            return 1

        if not indices:
            print("[FALTA] no hay índices en la tabla personas")
            return 1

        indexdefs = {name: definition for name, definition in indices}
        checks = {
            "search_vector": any("gin" in defn.lower() for defn in indexdefs.values()),
            "nombre_completo": any("gin_trgm_ops" in defn.lower() for defn in indexdefs.values()),
            "dni": any("dni" in name.lower() or "unique" in defn.lower() for name, defn in indexdefs.items()),
        }
        for nombre, ok in checks.items():
            estado = "OK" if ok else "FALTA"
            print(f"[{estado}] índice para {nombre}")
            errores += 0 if ok else 1

        for name, defn in indexdefs.items():
            print(f"        - {name}: {defn}")

    print()
    if errores:
        print(f"Hay {errores} pendientes. Revisa el setup de la base de datos.")
        return 1
    print("Base de datos lista para la API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
