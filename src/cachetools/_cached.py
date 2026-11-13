"""Function decorator helpers.

At least for now, the implementation prefers clarity and performance
over ease of maintenance, thus providing separate wrappers for all
valid combinations of parameters lock, condition and info.

"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false

__all__ = ()

import functools
import types

from ._decorator import (
    _BasicMixin,
    _ConditionInfoMixin,
    _ConditionMixin,
    _InfoMixin,
    _LockedInfoMixin,
    _LockedMixin,
)


class _WrapperBase:
    """Wrapper base class providing the public cache attributes."""

    def __init__(self, func, cache, key, lock=None, cond=None, group=None):
        # update first, so func.__dict__ cannot override wrapper state,
        # e.g. when stacking decorators
        functools.update_wrapper(self, func)
        self.cache = cache
        self.cache_key = key
        self.cache_lock = lock
        self.cache_condition = cond
        self.cache_group = group

    # descriptor and pickle support as for functools.lru_cache (C version)
    def __get__(self, obj, objtype=None):
        return self if obj is None else types.MethodType(self, obj)

    def __reduce__(self):
        return self.__qualname__

    def __repr__(self):
        return f"<cached {self.__wrapped__!r}>"


class _BasicWrapper(_WrapperBase, _BasicMixin):
    def __init__(self, func, cache, key, group=None):
        _WrapperBase.__init__(self, func, cache, key, group=group)
        _BasicMixin.__init__(self, func, group)


class _LockedWrapper(_WrapperBase, _LockedMixin):
    def __init__(self, func, cache, key, lock, group=None):
        _WrapperBase.__init__(self, func, cache, key, lock, group=group)
        _LockedMixin.__init__(self, func, group)


class _ConditionWrapper(_WrapperBase, _ConditionMixin):
    def __init__(self, func, cache, key, lock, cond, group=None):
        _WrapperBase.__init__(self, func, cache, key, lock, cond, group=group)
        _ConditionMixin.__init__(self, func, group)


class _InfoWrapper(_WrapperBase, _InfoMixin):
    def __init__(self, func, cache, key, info, group=None):
        _WrapperBase.__init__(self, func, cache, key, group=group)
        _InfoMixin.__init__(self, func, info, group)


class _LockedInfoWrapper(_WrapperBase, _LockedInfoMixin):
    def __init__(self, func, cache, key, lock, info, group=None):
        _WrapperBase.__init__(self, func, cache, key, lock, group=group)
        _LockedInfoMixin.__init__(self, func, info, group)


class _ConditionInfoWrapper(_WrapperBase, _ConditionInfoMixin):
    def __init__(self, func, cache, key, lock, cond, info, group=None):
        _WrapperBase.__init__(self, func, cache, key, lock, cond, group=group)
        _ConditionInfoMixin.__init__(self, func, info, group)


def _wrapper(func, cache, key, lock=None, cond=None, info=None, group=None):
    if info is not None:
        if cond is not None and lock is not None:
            wrapper = _ConditionInfoWrapper(func, cache, key, lock, cond, info, group)
        elif cond is not None:
            wrapper = _ConditionInfoWrapper(func, cache, key, cond, cond, info, group)
        elif lock is not None:
            wrapper = _LockedInfoWrapper(func, cache, key, lock, info, group)
        else:
            wrapper = _InfoWrapper(func, cache, key, info, group)
    else:
        if cond is not None and lock is not None:
            wrapper = _ConditionWrapper(func, cache, key, lock, cond, group)
        elif cond is not None:
            wrapper = _ConditionWrapper(func, cache, key, cond, cond, group)
        elif lock is not None:
            wrapper = _LockedWrapper(func, cache, key, lock, group)
        else:
            wrapper = _BasicWrapper(func, cache, key, group)
    return wrapper
