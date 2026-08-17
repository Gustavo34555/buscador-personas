import threading
import time
from collections import OrderedDict


class TTLCache:
    """Caché LRU con expiración por TTL y acceso seguro entre hilos."""

    def __init__(self, maxsize: int, ttl: float):
        self._data: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            now = time.time()
            item = self._data.get(key)
            if item is None:
                return None
            ts, value = item
            if now - ts >= self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            if len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
