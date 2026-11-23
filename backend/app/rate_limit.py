import threading
import time


class RateLimiter:
    """Limitador de peticiones por llave (ej. IP) en memoria, seguro entre hilos."""

    def __init__(self, max_hits: int, window: float):
        self.max_hits = max_hits
        self.window = window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._requests_since_sweep = 0

    def allow(self, key: str) -> tuple[bool, float]:
        """Devuelve (permitido, segundos_para_reintentar)."""
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.max_hits:
                retry = max(0.0, hits[0] + self.window - now)
                self._hits[key] = hits
                return False, retry
            hits.append(now)
            self._hits[key] = hits
            self._requests_since_sweep += 1
            if self._requests_since_sweep >= 200:
                self._sweep(now)
                self._requests_since_sweep = 0
            return True, 0.0

    def _sweep(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not any(now - t < self.window for t in v)]:
            del self._hits[key]

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisRateLimiter:
    """Ventana fija atómica compartida entre workers cuando hay Redis."""

    _SCRIPT = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    local ttl = redis.call('TTL', KEYS[1])
    return { current, ttl }
    """

    def __init__(self, max_hits: int, window: float, url: str, prefix: str):
        import redis  # import perezoso: la app funciona sin Redis

        self.max_hits = max_hits
        self.window = int(max(1, window))
        self.prefix = prefix
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._script = self._client.register_script(self._SCRIPT)

    def allow(self, key: str) -> tuple[bool, float]:
        current, ttl = self._script(keys=[f"{self.prefix}:{key}"], args=[self.window])
        current = int(current)
        retry = max(0.0, float(ttl))
        return current <= self.max_hits, 0.0 if current <= self.max_hits else retry

    def clear(self) -> None:
        # Solo para tests: elimina las claves de este limitador.
        for key in self._client.scan_iter(match=f"{self.prefix}:*"):
            self._client.delete(key)


def build_rate_limiter(
    *, max_hits: int, window: float, prefix: str, redis_url: str | None = None
) -> RateLimiter | RedisRateLimiter:
    """Usa Redis si está disponible; si no, cae al limitador en memoria."""
    if redis_url:
        try:
            return RedisRateLimiter(max_hits, window, redis_url, prefix)
        except Exception:
            pass
    return RateLimiter(max_hits, window)
