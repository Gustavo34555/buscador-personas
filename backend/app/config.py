import hashlib
import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("No se encontró DATABASE_URL en el archivo .env")

RUC_API_KEY = os.getenv("RUC_API_KEY", "")
RUC_API_BASE = os.getenv("RUC_API_BASE", "https://peruapi.com/api")

# API keys aceptadas (separadas por coma). Vacío = acceso abierto (solo desarrollo).
API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]

_ALLOWED = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = (
    [o.strip() for o in _ALLOWED.split(",") if o.strip()]
    if _ALLOWED
    else [
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
)

# Límites por IP en ventana de segundos (endpoints RUC)
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "30"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# Límites por IP (endpoints de búsqueda de personas)
SEARCH_RATE_LIMIT_MAX = int(os.getenv("SEARCH_RATE_LIMIT_MAX", "60"))
SEARCH_RATE_LIMIT_WINDOW = int(os.getenv("SEARCH_RATE_LIMIT_WINDOW", "60"))

# TTLs de caché en segundos
DNI_CACHE_TTL = int(os.getenv("DNI_CACHE_TTL", "300"))
BUSCAR_CACHE_TTL = int(os.getenv("BUSCAR_CACHE_TTL", "60"))
RUC_CACHE_TTL = int(os.getenv("RUC_CACHE_TTL", "3600"))

# Secreto para tokens de sesión del frontend.
# Se auto-genera a partir del primer API key si no se especifica.
_raw_secret = os.getenv("FRONTEND_TOKEN_SECRET", "")
if _raw_secret:
    FRONTEND_TOKEN_SECRET = _raw_secret
elif API_KEYS:
    FRONTEND_TOKEN_SECRET = hashlib.sha256(API_KEYS[0].encode()).hexdigest()
else:
    FRONTEND_TOKEN_SECRET = ""

FRONTEND_TOKEN_TTL = int(os.getenv("FRONTEND_TOKEN_TTL", "3600"))
