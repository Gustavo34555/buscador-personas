from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable

from app.config import CACHE_PREFIX, REDIS_URL

logger = logging.getLogger(__name__)


class TTLCache:
    """Caché LRU con expiración por TTL y acceso seguro entre hilos."""

    def __init__(self, maxsize: int, ttl: float):
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl
        self._lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}

    def get(self, key: str) -> Any | None:
        with self._lock:
            now = time.monotonic()
            item = self._data.get(key)
            if item is None:
                return None
            ts, value = item
            if now - ts >= self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            if len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def get_or_set(self, key: str, factory: Callable[[], Any]) -> Any:
        """Evita el cache stampede: solo un hilo calcula el valor por clave."""
        cached = self.get(key)
        if cached is not None:
            return cached

        with self._lock:
            lock = self._key_locks.setdefault(key, threading.Lock())
        with lock:
            cached = self.get(key)
            if cached is not None:
                return cached
            value = factory()
            if value is not None:
                self.set(key, value)
            return value

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class RedisTTLCache:
    """Caché compartida entre workers cuando REDIS_URL está configurado."""

    def __init__(self, name: str, ttl: float, prefix: str = CACHE_PREFIX):
        import redis  # import perezoso: la app funciona sin Redis

        self.ttl = int(ttl)
        self.prefix = f"{prefix}:{name}:"
        self._client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self._client.ping()

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Any | None:
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any) -> None:
        self._client.set(self._key(key), json.dumps(value, default=str), ex=self.ttl)

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def clear(self) -> None:
        # No se usa en producción; evita borrar claves de otros servicios.
        for key in self._client.scan_iter(match=f"{self.prefix}*"):
            self._client.delete(key)

    def get_or_set(self, key: str, factory: Callable[[], Any]) -> Any:
        """Anti-stampede distribuido con lock SET NX.

        Solo un worker calcula el valor; los demás esperan unos milisegundos
        y reutilizan la respuesta. Si el productor falla, cualquier esperador
        puede calcularlo para no dejar la petición colgada.
        """
        cached = self.get(key)
        if cached is not None:
            return cached

        lock_key = f"{self._key(key)}:lock"
        token = uuid.uuid4().hex
        acquired = self._client.set(lock_key, token, nx=True, ex=30)
        if not acquired:
            for _ in range(20):
                time.sleep(0.05)
                cached = self.get(key)
                if cached is not None:
                    return cached

        try:
            value = factory()
            if value is not None:
                self.set(key, value)
            return value
        finally:
            try:
                if self._client.get(lock_key) == token:
                    self._client.delete(lock_key)
            except Exception:
                logger.debug("No se pudo liberar el lock de caché", exc_info=True)

    def __len__(self) -> int:
        return sum(1 for _ in self._client.scan_iter(match=f"{self.prefix}*"))


def build_cache(name: str, maxsize: int, ttl: float) -> TTLCache | RedisTTLCache:
    """Crea una caché en Redis si está configurado; si no, en memoria."""
    if REDIS_URL:
        try:
            return RedisTTLCache(name=name, ttl=ttl)
        except Exception:
            logger.warning("Redis no disponible; usando caché en memoria para %s", name, exc_info=True)
    return TTLCache(maxsize=maxsize, ttl=ttl)
