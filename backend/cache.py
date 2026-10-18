"""Thread-safe TTL cache with invalidation support for Keystone graph metadata."""
import time
import threading
import fnmatch
from typing import Any, Optional


class TTLCache:
    def __init__(self, default_ttl: float = 60.0):
        self.default_ttl = default_ttl
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            val, expiry = entry
            if time.time() > expiry:
                del self._store[key]
                return None
            return val

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
        with self._lock:
            self._store[key] = (value, expiry)

    def invalidate(self, pattern: Optional[str] = None) -> None:
        with self._lock:
            if pattern is None:
                self._store.clear()
                return
            keys_to_del = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            for k in keys_to_del:
                del self._store[k]

    def clear(self) -> None:
        self.invalidate(None)


# Global singleton cache for graph metadata
METADATA_CACHE = TTLCache(default_ttl=45.0)
