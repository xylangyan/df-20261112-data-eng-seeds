"""Shared cache group metadata."""

__all__ = ()

import threading
import weakref


_registries = {}
_lock = threading.RLock()


def _get_registry(cache):
    cache_id = id(cache)
    with _lock:
        try:
            return _registries[cache_id]
        except KeyError:
            registry = {}
            _registries[cache_id] = registry
            try:
                finalizer = weakref.finalize(cache, _registries.pop, cache_id, None)
            except TypeError:
                pass
            else:
                finalizer.atexit = False
            return registry


def _set_group(cache, key, group):
    with _lock:
        _get_registry(cache)[key] = group


def _clear_registry(cache):
    with _lock:
        registry = _registries.get(id(cache))
        if registry is not None:
            registry.clear()


def _clear_group(cache, group):
    with _lock:
        registry = _registries.get(id(cache))
        if registry is None:
            return
        keys = [key for key, key_group in registry.items() if key_group == group]
        for key in keys:
            try:
                del cache[key]
            except KeyError:
                pass
            try:
                del registry[key]
            except KeyError:
                pass
