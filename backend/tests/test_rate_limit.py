import time

from app.cache import TTLCache
from app.rate_limit import RateLimiter


def test_rate_limiter_permite_y_bloquea():
    limiter = RateLimiter(max_hits=2, window=60)
    assert limiter.allow("a") == (True, 0.0)
    assert limiter.allow("a") == (True, 0.0)
    allowed, retry = limiter.allow("a")
    assert allowed is False
    assert 0 < retry <= 60
    assert limiter.allow("b") == (True, 0.0)


def test_rate_limiter_expira_ventana():
    limiter = RateLimiter(max_hits=1, window=0.05)
    assert limiter.allow("a") == (True, 0.0)
    assert limiter.allow("a")[0] is False
    time.sleep(0.07)
    assert limiter.allow("a") == (True, 0.0)


def test_rate_limiter_limpia_llaves_stale():
    limiter = RateLimiter(max_hits=100, window=0.05)
    limiter.allow("vieja")
    time.sleep(0.07)
    for i in range(201):
        limiter.allow(f"nueva{i}")
    assert "vieja" not in limiter._hits


def test_ttlcache_expira():
    cache = TTLCache(maxsize=10, ttl=0.05)
    cache.set("k", {"v": 1})
    assert cache.get("k") == {"v": 1}
    time.sleep(0.07)
    assert cache.get("k") is None


def test_ttlcache_lru():
    cache = TTLCache(maxsize=2, ttl=60)
    cache.set("a", {"v": 1})
    cache.set("b", {"v": 2})
    cache.get("a")
    cache.set("c", {"v": 3})
    assert cache.get("a") == {"v": 1}
    assert cache.get("b") is None
    assert cache.get("c") == {"v": 3}
