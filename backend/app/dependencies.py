from typing import Callable

from fastapi import HTTPException, Request

from app.config import RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, SEARCH_RATE_LIMIT_MAX, SEARCH_RATE_LIMIT_WINDOW
from app.rate_limit import RateLimiter

# Instancias globales de rate limiters
search_rate_limiter = RateLimiter(
    max_hits=SEARCH_RATE_LIMIT_MAX,
    window=SEARCH_RATE_LIMIT_WINDOW,
)

ruc_rate_limiter = RateLimiter(
    max_hits=RATE_LIMIT_MAX,
    window=RATE_LIMIT_WINDOW,
)


def get_client_host(request: Request) -> str:
    """Extrae la IP real del cliente del request, contemplando proxies inversos."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Tomar la primera IP de la cadena de proxies
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "desconocido"


def get_rate_limiter(limiter: RateLimiter, prefix: str) -> Callable[[Request], None]:
    """Retorna una dependencia que verifica el rate limit basado en la IP del cliente."""

    def _rate_limit_dependency(request: Request) -> None:
        client_ip = get_client_host(request)
        key = f"{prefix}:{client_ip}"
        allowed, retry = limiter.allow(key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Demasiadas consultas. Intenta más tarde.",
                headers={"Retry-After": str(int(retry))},
            )

    return _rate_limit_dependency


# Dependencias listas para usar en los routers
verify_search_rate_limit = get_rate_limiter(search_rate_limiter, "search")
verify_ruc_rate_limit = get_rate_limiter(ruc_rate_limiter, "ruc")
