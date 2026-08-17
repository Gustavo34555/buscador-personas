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
        now = time.time()
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
        for key in [
            k
            for k, v in self._hits.items()
            if not any(now - t < self.window for t in v)
        ]:
            del self._hits[key]

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
