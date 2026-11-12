import collections
import itertools
from .itertoolz import frequencies, pluck, getter
from .utils import no_default


__all__ = ('countby', 'partitionby', 'partitionby_iter')


class Partition:
    """ A single, lazily consumed run of equal keys

    Instances are produced by :func:`partitionby_iter` and are not normally
    constructed directly.
    """
    __slots__ = ('key', 'count', '_owner', '_reducer', '_init',
                 '_no_init', '_init_factory', '_value', '_started',
                 '_failed', '_error', '_complete', '_closed')

    def __init__(self, key, owner, reducer=None, init=no_default):
        self.key = key
        self.count = 0
        self._owner = owner
        self._reducer = reducer
        self._init = init
        self._no_init = init == no_default
        self._init_factory = init if callable(init) else lambda: init
        self._value = no_default
        self._started = False
        self._failed = False
        self._error = None
        self._complete = False
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise RuntimeError('partition is no longer active')
        if self._failed:
            raise RuntimeError('partition reducer failed') from self._error
        try:
            item = self._owner._pull(self)
        except StopIteration:
            self._complete = True
            raise
        self.count += 1
        if self._reducer is not None:
            try:
                if not self._started:
                    if self._no_init:
                        self._value = item
                    else:
                        self._value = self._init_factory()
                        self._value = self._reducer(self._value, item)
                    self._started = True
                else:
                    self._value = self._reducer(self._value, item)
            except Exception as error:
                self._failed = True
                self._error = error
                raise
        return item

    def _drain(self):
        while True:
            try:
                self._owner._pull(self)
            except StopIteration:
                break
            self.count += 1
        self._complete = True
        self._value = no_default

    def _close(self):
        self._closed = True

    def skip(self):
        """ Consume and discard the rest of this partition

        Advancing the outer ``partitionby_iter`` iterator also skips any
        remaining items in the current partition.  This method makes that
        behavior explicit.  A partition with a failed reducer has no summary
        and is drained without applying the reducer again.
        """
        if not self._complete:
            self._drain()
        if self._failed:
            return None
        return self.summary

    @property
    def summary(self):
        """ Summary for this partition

        The summary is available only after the partition has been fully
        consumed or skipped.  It contains the partition key, item count, and
        reduction result.  The result is ``no_default`` for skipped partitions
        and for partitions without a reducer.
        """
        if self._failed:
            raise RuntimeError('partition reducer failed') from self._error
        if not self._complete:
            raise RuntimeError('partition summary is not available until the '
                               'partition is exhausted')
        return PartitionSummary(self.key, self.count, self._value)


class PartitionSummary(collections.namedtuple('PartitionSummary',
                                              ('key', 'count', 'result'))):
    """ Key, count, and reduction result for an exhausted partition """
    __slots__ = ()


class _PartitionIterator:
    __slots__ = ('_source', '_func', '_reducer', '_init', '_current',
                 '_next_item', '_next_key', '_has_next')

    def __init__(self, source, func, reducer, init):
        self._source = source
        self._func = func
        self._reducer = reducer
        self._init = init
        self._current = None
        self._next_item = None
        self._next_key = None
        self._has_next = False

    def _next_source(self):
        return next(self._source)

    def _drain_current(self):
        if self._current is None:
            return
        if not self._current._complete:
            self._current._drain()
        self._current._close()

    def _pull(self, partition):
        if self._current is not partition:
            raise RuntimeError('partition is no longer active')
        if self._has_next:
            if self._next_key != partition.key:
                raise StopIteration
            item = self._next_item
            self._has_next = False
            return item

        item = self._next_source()
        key = self._func(item)
        if key != partition.key:
            self._next_item = item
            self._next_key = key
            self._has_next = True
            raise StopIteration
        return item

    def __iter__(self):
        return self

    def __next__(self):
        self._drain_current()
        if not self._has_next:
            self._next_item = self._next_source()
            self._next_key = self._func(self._next_item)
            self._has_next = True
        self._current = Partition(self._next_key, self, self._reducer,
                                  self._init)
        return self._current


def partitionby_iter(func, seq, reducer=None, init=no_default):
    """ Partition a sequence into lazily consumed runs

    Like :func:`partitionby`, this partitions adjacent items by ``func``.
    Unlike ``partitionby``, each run is not materialized.  Instead, this
    yields a :class:`Partition` object whose ``key`` and current ``count``
    can be inspected before consuming any more input.

    A partition is active only until the outer iterator is advanced.  If a
    partition is not fully consumed, advancing the outer iterator consumes
    and discards its remainder so that the next partition starts at the
    correct input position.  Calling ``skip()`` performs the same operation
    explicitly and does not apply the reducer to skipped items.  Once a
    partition is exhausted, its ``summary`` contains its key and total
    count; the reduction result is included for partitions that were fully
    reduced and is ``no_default`` for skipped partitions.

    If ``reducer`` is supplied, it is called as ``reducer(accumulator,
    item)`` for each item.  The ``init`` argument follows the same rules as
    in :func:`reduceby`: it may be a value or a zero-argument factory.  A
    reducer exception propagates immediately and leaves the input positioned
    after the item that caused the exception.

    Only adjacent items are grouped.  A key that occurs again later produces
    a new partition.

    >>> data = [('a', 1), ('a', 2), ('b', 3), ('a', 4)]
    >>> total = lambda value, item: value + item[1]
    >>> partitions = partitionby_iter(0, data, total, 0)
    >>> first = next(partitions)
    >>> first.key
    'a'
    >>> list(first)
    [('a', 1), ('a', 2)]
    >>> first.summary
    PartitionSummary(key='a', count=2, result=3)
    >>> second = next(partitions)
    >>> list(second)
    [('b', 3)]
    >>> second.summary
    PartitionSummary(key='b', count=1, result=3)
    >>> third = next(partitions)
    >>> list(third)
    [('a', 4)]
    >>> third.summary
    PartitionSummary(key='a', count=1, result=4)

    See Also:
        partitionby
        reduceby
        itertools.groupby
    """
    if not callable(func):
        func = getter(func)
    return _PartitionIterator(iter(seq), func, reducer, init)


def countby(key, seq):
    """ Count elements of a collection by a key function

    >>> countby(len, ['cat', 'mouse', 'dog'])
    {3: 2, 5: 1}

    >>> def iseven(x): return x % 2 == 0
    >>> countby(iseven, [1, 2, 3])  # doctest:+SKIP
    {True: 1, False: 2}

    See Also:
        groupby
    """
    if not callable(key):
        key = getter(key)
    return frequencies(map(key, seq))


def partitionby(func, seq):
    """ Partition a sequence according to a function

    Partition `s` into a sequence of lists such that, when traversing
    `s`, every time the output of `func` changes a new list is started
    and that and subsequent items are collected into that list.

    >>> is_space = lambda c: c == " "
    >>> list(partitionby(is_space, "I have space"))
    [('I',), (' ',), ('h', 'a', 'v', 'e'), (' ',), ('s', 'p', 'a', 'c', 'e')]

    >>> is_large = lambda x: x > 10
    >>> list(partitionby(is_large, [1, 2, 1, 99, 88, 33, 99, -1, 5]))
    [(1, 2, 1), (99, 88, 33, 99), (-1, 5)]

    See also:
        partition
        groupby
        itertools.groupby
    """
    return map(tuple, pluck(1, itertools.groupby(seq, key=func)))
