"""Mixin helpers.

At least for now, the implementation prefers clarity and performance
over ease of maintenance, thus providing separate wrappers for all
valid combinations of parameters lock, condition and info.

"""

# pyright: reportAttributeAccessIssue=false

__all__ = ()

from ._groups import _clear_group, _clear_registry, _set_group


class _BasicMixin:
    def __init__(self, func, group=None):
        self.__func = func
        self.__group = group

    def __call__(self, /, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)

        try:
            return cache[key]
        except KeyError:
            pass  # key not found
        val = self.__func(*args, **kwargs)
        try:
            cache[key] = val
        except ValueError:
            pass  # value too large
        else:
            if self.__group is not None:
                _set_group(cache, key, self.__group)
        return val

    def cache_clear(self, group=None):
        if group is None:
            self.cache.clear()
            _clear_registry(self.cache)
        else:
            _clear_group(self.cache, group)

    cache_invalidate = cache_clear


class _LockedMixin:
    def __init__(self, func, group=None):
        self.__func = func
        self.__group = group

    def __call__(self, /, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock

        with lock:
            try:
                return cache[key]
            except KeyError:
                pass  # key not found
        val = self.__func(*args, **kwargs)
        with lock:
            try:
                # In case of a race condition, i.e. if another thread
                # stored a value for this key while we were calling
                # self.__func(), prefer the cached value.
                result = cache.setdefault(key, val)
            except ValueError:
                return val  # value too large
            if self.__group is not None:
                _set_group(cache, key, self.__group)
            return result

    def cache_clear(self, group=None):
        with self.cache_lock:
            if group is None:
                self.cache.clear()
                _clear_registry(self.cache)
            else:
                _clear_group(self.cache, group)

    cache_invalidate = cache_clear


class _ConditionMixin:
    def __init__(self, func, group=None):
        self.__func = func
        self.__group = group
        self.__pending = set()

    def __call__(self, /, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock
        cond = self.cache_condition

        with lock:
            # apparently significantly faster than cond.wait_for(...)
            while key in self.__pending:
                cond.wait()
            try:
                return cache[key]
            except KeyError:
                self.__pending.add(key)
        try:
            val = self.__func(*args, **kwargs)
            with lock:
                try:
                    cache[key] = val
                except ValueError:
                    pass  # value too large
                else:
                    if self.__group is not None:
                        _set_group(cache, key, self.__group)
                return val
        finally:
            with lock:
                self.__pending.remove(key)
                cond.notify_all()

    def cache_clear(self, group=None):
        with self.cache_lock:
            if group is None:
                self.cache.clear()
                _clear_registry(self.cache)
            else:
                _clear_group(self.cache, group)

    cache_invalidate = cache_clear


class _InfoMixin:
    def __init__(self, func, info, group=None):
        self.__func = func
        self.__info = info
        self.__group = group
        self.__hits = self.__misses = 0

    def __call__(self, /, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)

        try:
            result = cache[key]
            self.__hits += 1
            return result
        except KeyError:
            self.__misses += 1
        val = self.__func(*args, **kwargs)
        try:
            cache[key] = val
        except ValueError:
            pass  # value too large
        else:
            if self.__group is not None:
                _set_group(cache, key, self.__group)
        return val

    def cache_clear(self, group=None):
        if group is None:
            self.cache.clear()
            _clear_registry(self.cache)
            self.__hits = self.__misses = 0
        else:
            _clear_group(self.cache, group)

    cache_invalidate = cache_clear

    def cache_info(self):
        return self.__info(self.cache, self.__hits, self.__misses)


class _LockedInfoMixin:
    def __init__(self, func, info, group=None):
        self.__func = func
        self.__info = info
        self.__group = group
        self.__hits = self.__misses = 0

    def __call__(self, /, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock

        with lock:
            try:
                result = cache[key]
                self.__hits += 1
                return result
            except KeyError:
                self.__misses += 1
        val = self.__func(*args, **kwargs)
        with lock:
            try:
                # In case of a race condition, i.e. if another thread
                # stored a value for this key while we were calling
                # self.__func(), prefer the cached value.
                result = cache.setdefault(key, val)
            except ValueError:
                return val  # value too large
            if self.__group is not None:
                _set_group(cache, key, self.__group)
            return result

    def cache_clear(self, group=None):
        with self.cache_lock:
            if group is None:
                self.cache.clear()
                _clear_registry(self.cache)
                self.__hits = self.__misses = 0
            else:
                _clear_group(self.cache, group)

    cache_invalidate = cache_clear

    def cache_info(self):
        with self.cache_lock:
            return self.__info(self.cache, self.__hits, self.__misses)


class _ConditionInfoMixin:
    def __init__(self, func, info, group=None):
        self.__func = func
        self.__info = info
        self.__group = group
        self.__hits = self.__misses = 0
        self.__pending = set()

    def __call__(self, /, *args, **kwargs):
        cache = self.cache
        key = self.cache_key(*args, **kwargs)
        lock = self.cache_lock
        cond = self.cache_condition

        with lock:
            # apparently significantly faster than cond.wait_for(...)
            while key in self.__pending:
                cond.wait()
            try:
                result = cache[key]
                self.__hits += 1
                return result
            except KeyError:
                self.__pending.add(key)
                self.__misses += 1
        try:
            val = self.__func(*args, **kwargs)
            with lock:
                try:
                    cache[key] = val
                except ValueError:
                    pass  # value too large
                else:
                    if self.__group is not None:
                        _set_group(cache, key, self.__group)
                return val
        finally:
            with lock:
                self.__pending.remove(key)
                cond.notify_all()

    def cache_clear(self, group=None):
        with self.cache_lock:
            if group is None:
                self.cache.clear()
                _clear_registry(self.cache)
                self.__hits = self.__misses = 0
            else:
                _clear_group(self.cache, group)

    cache_invalidate = cache_clear

    def cache_info(self):
        with self.cache_lock:
            return self.__info(self.cache, self.__hits, self.__misses)
