import operator
import collections
from functools import reduce
from collections.abc import Mapping

__all__ = ('merge', 'merge_with', 'deep_merge', 'valmap', 'keymap', 'itemmap',
           'valfilter', 'keyfilter', 'itemfilter',
           'assoc', 'dissoc', 'assoc_in', 'update_in', 'get_in')


def _get_factory(f, kwargs):
    factory = kwargs.pop('factory', dict)
    if kwargs:
        raise TypeError("{}() got an unexpected keyword argument "
                        "'{}'".format(f.__name__, kwargs.popitem()[0]))
    return factory


def merge(*dicts, **kwargs):
    """ Merge a collection of dictionaries

    >>> merge({1: 'one'}, {2: 'two'})
    {1: 'one', 2: 'two'}

    Later dictionaries have precedence

    >>> merge({1: 2, 3: 4}, {3: 3, 4: 4})
    {1: 2, 3: 3, 4: 4}

    See Also:
        merge_with
    """
    if len(dicts) == 1 and not isinstance(dicts[0], Mapping):
        dicts = dicts[0]
    factory = _get_factory(merge, kwargs)

    rv = factory()
    for d in dicts:
        rv.update(d)
    return rv


def merge_with(func, *dicts, **kwargs):
    """ Merge dictionaries and apply function to combined values

    A key may occur in more than one dict, and all values mapped from the key
    will be passed to the function as a list, such as func([val1, val2, ...]).

    >>> merge_with(sum, {1: 1, 2: 2}, {1: 10, 2: 20})
    {1: 11, 2: 22}

    >>> merge_with(first, {1: 1, 2: 2}, {2: 20, 3: 30})  # doctest: +SKIP
    {1: 1, 2: 2, 3: 30}

    See Also:
        merge
    """
    if len(dicts) == 1 and not isinstance(dicts[0], Mapping):
        dicts = dicts[0]
    factory = _get_factory(merge_with, kwargs)

    values = collections.defaultdict(lambda: [].append)
    for d in dicts:
        for k, v in d.items():
            values[k](v)

    result = factory()
    for k, v in values.items():
        result[k] = func(v.__self__)
    return result


_MISSING = object()


def deep_merge(*dicts, **kwargs):
    """ Deeply merge nested mappings with per-field conflict resolution

    Sources are merged key by key, recursing into nested mappings.
    Semantics for each key:

    - A key missing from a source means that source did not report it.
    - An explicit ``None`` value retracts any previously reported value;
      the key is dropped from the result and its full path is recorded
      in the report under ``'cleared'``.
    - If several sources report different truthy values for the same
      field, a per-field decision is made: a rule registered under the
      full key path in ``rules`` wins, otherwise the last source wins.
      Either way the field's full path, the competing values, and the
      source order are recorded in the report under ``'conflicts'``.

    ``rules`` maps a full key path (a tuple of keys) to a function
    taking the list of reported values and returning the value to keep.

    Inputs are never mutated, and mappings obtained from a one-shot
    iterable are read exactly once.  A custom ``factory`` is used for
    the result and for every nested mapping it creates.

    Returns a ``(result, report)`` pair where ``report`` is a dict with
    ``'conflicts'`` and ``'cleared'`` lists of full key paths.

    >>> result, report = deep_merge({'a': 1, 'b': {'x': 1}},
    ...                             {'b': {'x': 2, 'y': None}})
    >>> result
    {'a': 1, 'b': {'x': 2}}
    >>> report['cleared']
    [('b', 'y')]

    >>> result, report = deep_merge({'a': 1}, {'a': 2},
    ...                             rules={('a',): min})
    >>> result
    {'a': 1}
    >>> report['conflicts']
    [(('a',), [1, 2], (0, 1))]

    See Also:
        merge
        merge_with
    """
    if len(dicts) == 1 and not isinstance(dicts[0], Mapping):
        dicts = tuple(dicts[0])
    rules = kwargs.pop('rules', None) or {}
    factory = _get_factory(deep_merge, kwargs)

    conflicts = []
    cleared = []

    def merge_maps(sources, path):
        # Read each source exactly once, collecting per-key entries as
        # (source_index, value) pairs in source order.
        entries = {}
        for index, d in enumerate(sources):
            for k, v in d.items():
                entries.setdefault(k, []).append((index, v))

        rv = factory()
        for k, pairs in entries.items():
            key_path = path + (k,)
            value = merge_values(pairs, key_path)
            if value is not _MISSING:
                rv[k] = value
        return rv

    def merge_values(pairs, path):
        values = [v for _, v in pairs]
        if values[-1] is None:
            # The latest report retracts the field entirely.
            cleared.append(path)
            return _MISSING
        values = [v for v in values if v is not None]
        if not values:
            return _MISSING
        if all(isinstance(v, Mapping) for v in values):
            return merge_maps(values, path)
        if any(isinstance(v, Mapping) for v in values):
            # Branch shapes disagree: some sources report a nested
            # mapping, others a plain value.  Record and keep the last.
            kinds = ['mapping' if isinstance(v, Mapping) else 'value'
                     for v in values]
            sources = tuple(i for i, v in pairs if v is not None)
            conflicts.append((path, kinds, sources))
            if path in rules:
                return rules[path](values)
            return values[-1]
        distinct = []
        for v in values:
            if v not in distinct:
                distinct.append(v)
        if len(distinct) == 1:
            return distinct[0]
        sources = tuple(i for i, v in pairs if v is not None)
        conflicts.append((path, values, sources))
        if path in rules:
            return rules[path](values)
        return values[-1]

    result = merge_maps(dicts, ())
    report = {'conflicts': conflicts, 'cleared': cleared}
    return result, report


def valmap(func, d, factory=dict):
    """ Apply function to values of dictionary

    >>> bills = {"Alice": [20, 15, 30], "Bob": [10, 35]}
    >>> valmap(sum, bills)  # doctest: +SKIP
    {'Alice': 65, 'Bob': 45}

    See Also:
        keymap
        itemmap
    """
    rv = factory()
    rv.update(zip(d.keys(), map(func, d.values())))
    return rv


def keymap(func, d, factory=dict):
    """ Apply function to keys of dictionary

    >>> bills = {"Alice": [20, 15, 30], "Bob": [10, 35]}
    >>> keymap(str.lower, bills)  # doctest: +SKIP
    {'alice': [20, 15, 30], 'bob': [10, 35]}

    See Also:
        valmap
        itemmap
    """
    rv = factory()
    rv.update(zip(map(func, d.keys()), d.values()))
    return rv


def itemmap(func, d, factory=dict):
    """ Apply function to items of dictionary

    >>> accountids = {"Alice": 10, "Bob": 20}
    >>> itemmap(reversed, accountids)  # doctest: +SKIP
    {10: "Alice", 20: "Bob"}

    See Also:
        keymap
        valmap
    """
    rv = factory()
    rv.update(map(func, d.items()))
    return rv


def valfilter(predicate, d, factory=dict):
    """ Filter items in dictionary by value

    >>> iseven = lambda x: x % 2 == 0
    >>> d = {1: 2, 2: 3, 3: 4, 4: 5}
    >>> valfilter(iseven, d)
    {1: 2, 3: 4}

    See Also:
        keyfilter
        itemfilter
        valmap
    """
    rv = factory()
    for k, v in d.items():
        if predicate(v):
            rv[k] = v
    return rv


def keyfilter(predicate, d, factory=dict):
    """ Filter items in dictionary by key

    >>> iseven = lambda x: x % 2 == 0
    >>> d = {1: 2, 2: 3, 3: 4, 4: 5}
    >>> keyfilter(iseven, d)
    {2: 3, 4: 5}

    See Also:
        valfilter
        itemfilter
        keymap
    """
    rv = factory()
    for k, v in d.items():
        if predicate(k):
            rv[k] = v
    return rv


def itemfilter(predicate, d, factory=dict):
    """ Filter items in dictionary by item

    >>> def isvalid(item):
    ...     k, v = item
    ...     return k % 2 == 0 and v < 4

    >>> d = {1: 2, 2: 3, 3: 4, 4: 5}
    >>> itemfilter(isvalid, d)
    {2: 3}

    See Also:
        keyfilter
        valfilter
        itemmap
    """
    rv = factory()
    for item in d.items():
        if predicate(item):
            k, v = item
            rv[k] = v
    return rv


def assoc(d, key, value, factory=dict):
    """ Return a new dict with new key value pair

    New dict has d[key] set to value. Does not modify the initial dictionary.

    >>> assoc({'x': 1}, 'x', 2)
    {'x': 2}
    >>> assoc({'x': 1}, 'y', 3)   # doctest: +SKIP
    {'x': 1, 'y': 3}
    """
    d2 = factory()
    d2.update(d)
    d2[key] = value
    return d2


def dissoc(d, *keys, **kwargs):
    """ Return a new dict with the given key(s) removed.

    New dict has d[key] deleted for each supplied key.
    Does not modify the initial dictionary.

    >>> dissoc({'x': 1, 'y': 2}, 'y')
    {'x': 1}
    >>> dissoc({'x': 1, 'y': 2}, 'y', 'x')
    {}
    >>> dissoc({'x': 1}, 'y') # Ignores missing keys
    {'x': 1}
    """
    factory = _get_factory(dissoc, kwargs)
    d2 = factory()

    if len(keys) < len(d) * .6:
        d2.update(d)
        for key in keys:
            if key in d2:
                del d2[key]
    else:
        remaining = set(d)
        remaining.difference_update(keys)
        for k in remaining:
            d2[k] = d[k]
    return d2


def assoc_in(d, keys, value, factory=dict):
    """ Return a new dict with new, potentially nested, key value pair

    >>> purchase = {'name': 'Alice',
    ...             'order': {'items': ['Apple', 'Orange'],
    ...                       'costs': [0.50, 1.25]},
    ...             'credit card': '5555-1234-1234-1234'}
    >>> assoc_in(purchase, ['order', 'costs'], [0.25, 1.00]) # doctest: +SKIP
    {'credit card': '5555-1234-1234-1234',
     'name': 'Alice',
     'order': {'costs': [0.25, 1.00], 'items': ['Apple', 'Orange']}}
    """
    return update_in(d, keys, lambda x: value, value, factory)


def update_in(d, keys, func, default=None, factory=dict):
    """ Update value in a (potentially) nested dictionary

    inputs:
    d - dictionary on which to operate
    keys - list or tuple giving the location of the value to be changed in d
    func - function to operate on that value

    If keys == [k0,..,kX] and d[k0]..[kX] == v, update_in returns a copy of the
    original dictionary with v replaced by func(v), but does not mutate the
    original dictionary.

    If k0 is not a key in d, update_in creates nested dictionaries to the depth
    specified by the keys, with the innermost value set to func(default).

    >>> inc = lambda x: x + 1
    >>> update_in({'a': 0}, ['a'], inc)
    {'a': 1}

    >>> transaction = {'name': 'Alice',
    ...                'purchase': {'items': ['Apple', 'Orange'],
    ...                             'costs': [0.50, 1.25]},
    ...                'credit card': '5555-1234-1234-1234'}
    >>> update_in(transaction, ['purchase', 'costs'], sum) # doctest: +SKIP
    {'credit card': '5555-1234-1234-1234',
     'name': 'Alice',
     'purchase': {'costs': 1.75, 'items': ['Apple', 'Orange']}}

    >>> # updating a value when k0 is not in d
    >>> update_in({}, [1, 2, 3], str, default="bar")
    {1: {2: {3: 'bar'}}}
    >>> update_in({1: 'foo'}, [2, 3, 4], inc, 0)
    {1: 'foo', 2: {3: {4: 1}}}
    """
    ks = iter(keys)
    k = next(ks)

    rv = inner = factory()
    rv.update(d)

    for key in ks:
        if k in d:
            d = d[k]
            dtemp = factory()
            dtemp.update(d)
        else:
            d = dtemp = factory()

        inner[k] = inner = dtemp
        k = key

    if k in d:
        inner[k] = func(d[k])
    else:
        inner[k] = func(default)
    return rv


def get_in(keys, coll, default=None, no_default=False):
    """ Returns coll[i0][i1]...[iX] where [i0, i1, ..., iX]==keys.

    If coll[i0][i1]...[iX] cannot be found, returns ``default``, unless
    ``no_default`` is specified, then it raises KeyError or IndexError.

    ``get_in`` is a generalization of ``operator.getitem`` for nested data
    structures such as dictionaries and lists.

    >>> transaction = {'name': 'Alice',
    ...                'purchase': {'items': ['Apple', 'Orange'],
    ...                             'costs': [0.50, 1.25]},
    ...                'credit card': '5555-1234-1234-1234'}
    >>> get_in(['purchase', 'items', 0], transaction)
    'Apple'
    >>> get_in(['name'], transaction)
    'Alice'
    >>> get_in(['purchase', 'total'], transaction)
    >>> get_in(['purchase', 'items', 'apple'], transaction)
    >>> get_in(['purchase', 'items', 10], transaction)
    >>> get_in(['purchase', 'total'], transaction, 0)
    0
    >>> get_in(['y'], {}, no_default=True)
    Traceback (most recent call last):
        ...
    KeyError: 'y'

    See Also:
        itertoolz.get
        operator.getitem
    """
    try:
        return reduce(operator.getitem, keys, coll)
    except (KeyError, IndexError, TypeError):
        if no_default:
            raise
        return default
