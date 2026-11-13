"""Scheduling Utilities."""

from __future__ import annotations

from itertools import count

from .imports import symbol_by_name

__all__ = (
    'FairCycle', 'QoSFairCycle',
    'priority_cycle', 'round_robin_cycle', 'sorted_cycle',
)

CYCLE_ALIASES = {
    'priority': 'kombu.utils.scheduling:priority_cycle',
    'round_robin': 'kombu.utils.scheduling:round_robin_cycle',
    'sorted': 'kombu.utils.scheduling:sorted_cycle',
}


class FairCycle:
    """Cycle between resources.

    Consume from a set of resources, where each resource gets
    an equal chance to be consumed from.

    Arguments:
    ---------
        fun (Callable): Callback to call.
        resources (Sequence[Any]): List of resources.
        predicate (type): Exception predicate.
    """

    def __init__(self, fun, resources, predicate=Exception):
        self.fun = fun
        self.resources = resources
        self.predicate = predicate
        self.pos = 0

    def _next(self):
        while 1:
            try:
                resource = self.resources[self.pos]
                self.pos += 1
                return resource
            except IndexError:
                self.pos = 0
                if not self.resources:
                    raise self.predicate()

    def get(self, callback, **kwargs):
        """Get from next resource."""
        for tried in count(0):  # for infinity
            resource = self._next()
            try:
                return self.fun(resource, callback, **kwargs)
            except self.predicate:
                # reraise when retries exhausted.
                if tried >= len(self.resources) - 1:
                    raise

    def close(self):
        """Close cycle."""

    def __repr__(self):
        """``repr(cycle)``."""
        return '<FairCycle: {self.pos}/{size} {self.resources}>'.format(
            self=self, size=len(self.resources))


class QoSFairCycle:
    """Round-robin cycle that honors per-channel prefetch limits.

    Like :class:`FairCycle`, each resource gets an equal chance, but one
    full pass over :attr:`resources` is treated as an explicit round:

    - empty resources (those raising :attr:`predicate`) are skipped and the
      round continues with the next resource,
    - resources whose channel already holds as many unacknowledged messages
      as its ``prefetch_count`` allows are skipped without consuming from
      them. A skipped resource stays part of the rotation, so it is revisited
      as soon as an acknowledgement reopens the prefetch budget,
    - fairness only applies *between* queues. Message order inside a single
      queue is left entirely to the transport (FIFO for the in-memory
      transport).

    Arguments:
    ---------
        fun (Callable): Callback to call.
        resources (Sequence[Any]): List of resources.
        predicate (type): Exception raised when a resource has no message.
        can_consume (Callable): Optional predicate returning :const:`True`
            when the channel may receive another message. When it returns
            :const:`False`, every resource is skipped for this call.
    """

    def __init__(self, fun, resources, predicate=Exception,
                 can_consume=None):
        self.fun = fun
        self.resources = resources
        self.predicate = predicate
        self.can_consume = can_consume
        self.pos = 0

    def get(self, callback, **kwargs):
        """Get one message from the next eligible resource."""
        if self.can_consume is not None and not self.can_consume():
            raise self.predicate()
        resources = self.resources
        size = len(resources)
        if not size:
            raise self.predicate()
        # One call scans each resource at most once, starting at the cursor.
        # The cursor advances by one per call, so consecutive calls rotate
        # the starting point and no resource can starve the others.
        start = self.pos % size
        self.pos = (start + 1) % size
        for offset in range(size):
            resource = resources[(start + offset) % size]
            try:
                return self.fun(resource, callback, **kwargs)
            except self.predicate:
                continue
        raise self.predicate()

    def close(self):
        """Close cycle."""

    def __repr__(self):
        """``repr(cycle)``."""
        return '<QoSFairCycle: {self.pos}/{size} {self.resources}>'.format(
            self=self, size=len(self.resources))


class round_robin_cycle:
    """Iterator that cycles between items in round-robin."""

    def __init__(self, it=None):
        self.items = it if it is not None else []

    def update(self, it):
        """Update items from iterable."""
        self.items[:] = it

    def consume(self, n):
        """Consume n items."""
        return self.items[:n]

    def rotate(self, last_used):
        """Move most recently used item to end of list."""
        items = self.items
        try:
            items.append(items.pop(items.index(last_used)))
        except ValueError:
            pass
        return last_used


class priority_cycle(round_robin_cycle):
    """Cycle that repeats items in order."""

    def rotate(self, last_used):
        """Unused in this implementation."""


class sorted_cycle(priority_cycle):
    """Cycle in sorted order."""

    def consume(self, n):
        """Consume n items."""
        return sorted(self.items[:n])


def cycle_by_name(name):
    """Get cycle class by name."""
    return symbol_by_name(name, CYCLE_ALIASES)
