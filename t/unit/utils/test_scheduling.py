from __future__ import annotations

from unittest.mock import Mock

import pytest

from kombu.utils.scheduling import (FairCycle, QoSFairCycle, cycle_by_name)


class MyEmpty(Exception):
    pass


def consume(fun, n):
    r = []
    for i in range(n):
        r.append(fun(Mock(name='callback')))
    return r


class test_FairCycle:

    def test_cycle(self):
        resources = ['a', 'b', 'c', 'd', 'e']
        callback = Mock(name='callback')

        def echo(r, timeout=None):
            return r

        # cycle should be ['a', 'b', 'c', 'd', 'e', ... repeat]
        cycle = FairCycle(echo, resources, MyEmpty)
        for i in range(len(resources)):
            assert cycle.get(callback) == resources[i]
        for i in range(len(resources)):
            assert cycle.get(callback) == resources[i]

    def test_cycle_breaks(self):
        resources = ['a', 'b', 'c', 'd', 'e']

        def echo(r, callback):
            if r == 'c':
                raise MyEmpty(r)
            return r

        cycle = FairCycle(echo, resources, MyEmpty)
        assert consume(cycle.get, len(resources)) == [
            'a', 'b', 'd', 'e', 'a',
        ]
        assert consume(cycle.get, len(resources)) == [
            'b', 'd', 'e', 'a', 'b',
        ]
        cycle2 = FairCycle(echo, ['c', 'c'], MyEmpty)
        with pytest.raises(MyEmpty):
            consume(cycle2.get, 3)

    def test_cycle_no_resources(self):
        cycle = FairCycle(None, [], MyEmpty)
        cycle.pos = 10

        with pytest.raises(MyEmpty):
            cycle._next()

    def test__repr__(self):
        assert repr(FairCycle(lambda x: x, [1, 2, 3], MyEmpty))


class test_QoSFairCycle:

    def setup_method(self):
        self.state = {
            'a': ['a1', 'a2', 'a3', 'a4'],
            'b': ['b1', 'b2'],
            'c': [],
        }

        def fun(resource, callback, **kwargs):
            items = self.state[resource]
            if not items:
                raise MyEmpty(resource)
            return items.pop(0)

        self.fun = fun

    def make(self, resources, can_consume=None):
        return QoSFairCycle(
            self.fun, resources, MyEmpty, can_consume=can_consume)

    def test_round_robin_order(self):
        cycle = self.make(['a', 'b'])
        # each get is one round start: a, then b, then a, ...
        assert consume(cycle.get, 6) == [
            'a1', 'b1', 'a2', 'b2', 'a3', 'a4',
        ]

    def test_empty_resources_are_skipped_within_one_round(self):
        cycle = self.make(['a', 'c', 'b'])
        # 'c' is empty: it must be skipped without ending the round.
        # round 1 starts at a, round 2 starts at c -> falls through to b,
        # round 3 starts at b, round 4 starts at a again.
        assert consume(cycle.get, 4) == ['a1', 'b1', 'b2', 'a2']
        # cursor kept rotating past the empty resource
        assert cycle.pos == 4 % 3

    def test_all_empty_raises_predicate(self):
        for items in self.state.values():
            items.clear()
        cycle = self.make(['a', 'b'])
        with pytest.raises(MyEmpty):
            cycle.get(Mock())

    def test_no_resources_raises_predicate(self):
        cycle = self.make([])
        with pytest.raises(MyEmpty):
            cycle.get(Mock())

    def test_can_consume_false_skips_every_resource(self):
        gate = Mock(name='can_consume', return_value=False)
        cycle = self.make(['a', 'b'], can_consume=gate)
        with pytest.raises(MyEmpty):
            cycle.get(Mock())
        # nothing was popped from the backing resources
        assert self.state == {
            'a': ['a1', 'a2', 'a3', 'a4'],
            'b': ['b1', 'b2'],
            'c': [],
        }
        assert cycle.pos == 0

    def test_can_consume_reopens_after_ack(self):
        allowed = {'value': False}
        cycle = self.make(
            ['a', 'b'], can_consume=lambda: allowed['value'])
        with pytest.raises(MyEmpty):
            cycle.get(Mock())
        # an acknowledgement reopens the prefetch budget
        allowed['value'] = True
        assert cycle.get(Mock()) == 'a1'

    def test_resources_shrunk_does_not_break_round(self):
        resources = ['a', 'b']
        cycle = self.make(resources)
        assert cycle.get(Mock()) == 'a1'
        # basic_cancel removed the remaining resource before the next get
        resources.remove('b')
        assert cycle.get(Mock()) == 'a2'
        assert cycle.pos == 0

    def test__repr__(self):
        assert repr(self.make(['a', 'b']))


def test_round_robin_cycle():
    it = cycle_by_name('round_robin')(['A', 'B', 'C'])
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('B')
    assert it.consume(3) == ['A', 'C', 'B']
    it.rotate('A')
    assert it.consume(3) == ['C', 'B', 'A']
    it.rotate('A')
    assert it.consume(3) == ['C', 'B', 'A']
    it.rotate('C')
    assert it.consume(3) == ['B', 'A', 'C']


def test_priority_cycle():
    it = cycle_by_name('priority')(['A', 'B', 'C'])
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('B')
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('A')
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('A')
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('C')
    assert it.consume(3) == ['A', 'B', 'C']


def test_sorted_cycle():
    it = cycle_by_name('sorted')(['B', 'C', 'A'])
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('B')
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('A')
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('A')
    assert it.consume(3) == ['A', 'B', 'C']
    it.rotate('C')
    assert it.consume(3) == ['A', 'B', 'C']
