import toolz


__all__ = ['merge_with', 'merge', 'deep_merge']


@toolz.curry
def merge_with(func, d, *dicts, **kwargs):
    return toolz.merge_with(func, d, *dicts, **kwargs)


@toolz.curry
def merge(d, *dicts, **kwargs):
    return toolz.merge(d, *dicts, **kwargs)


@toolz.curry
def deep_merge(d, *dicts, **kwargs):
    return toolz.deep_merge(d, *dicts, **kwargs)


merge_with.__doc__ = toolz.merge_with.__doc__
merge.__doc__ = toolz.merge.__doc__
deep_merge.__doc__ = toolz.deep_merge.__doc__
