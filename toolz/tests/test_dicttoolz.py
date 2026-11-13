from collections import defaultdict as _defaultdict
from collections.abc import Mapping
import os
from toolz.dicttoolz import (merge, merge_with, deep_merge, valmap, keymap,
                             update_in, assoc, dissoc, keyfilter, valfilter,
                             itemmap, itemfilter, assoc_in, get_in)
from toolz.functoolz import identity
from toolz.utils import raises


def inc(x):
    return x + 1


def iseven(i):
    return i % 2 == 0


class TestDict:
    """Test typical usage: dict inputs, no factory keyword.

    Class attributes:
        D: callable that inputs a dict and creates or returns a MutableMapping
        kw: kwargs dict to specify "factory" keyword (if applicable)
    """
    D = dict
    kw = {}

    def test_merge(self):
        D, kw = self.D, self.kw
        assert merge(D({1: 1, 2: 2}), D({3: 4}), **kw) == D({1: 1, 2: 2, 3: 4})

    def test_merge_iterable_arg(self):
        D, kw = self.D, self.kw
        assert merge([D({1: 1, 2: 2}), D({3: 4})], **kw) == D({1: 1, 2: 2, 3: 4})

    def test_merge_with(self):
        D, kw = self.D, self.kw
        dicts = D({1: 1, 2: 2}), D({1: 10, 2: 20})
        assert merge_with(sum, *dicts, **kw) == D({1: 11, 2: 22})
        assert merge_with(tuple, *dicts, **kw) == D({1: (1, 10), 2: (2, 20)})

        dicts = D({1: 1, 2: 2, 3: 3}), D({1: 10, 2: 20})
        assert merge_with(sum, *dicts, **kw) == D({1: 11, 2: 22, 3: 3})
        assert merge_with(tuple, *dicts, **kw) == D({1: (1, 10), 2: (2, 20), 3: (3,)})

        assert not merge_with(sum)

    def test_merge_with_iterable_arg(self):
        D, kw = self.D, self.kw
        dicts = D({1: 1, 2: 2}), D({1: 10, 2: 20})
        assert merge_with(sum, *dicts, **kw) == D({1: 11, 2: 22})
        assert merge_with(sum, dicts, **kw) == D({1: 11, 2: 22})
        assert merge_with(sum, iter(dicts), **kw) == D({1: 11, 2: 22})

    def test_valmap(self):
        D, kw = self.D, self.kw
        assert valmap(inc, D({1: 1, 2: 2}), **kw) == D({1: 2, 2: 3})

    def test_keymap(self):
        D, kw = self.D, self.kw
        assert keymap(inc, D({1: 1, 2: 2}), **kw) == D({2: 1, 3: 2})

    def test_itemmap(self):
        D, kw = self.D, self.kw
        assert itemmap(reversed, D({1: 2, 2: 4}), **kw) == D({2: 1, 4: 2})

    def test_valfilter(self):
        D, kw = self.D, self.kw
        assert valfilter(iseven, D({1: 2, 2: 3}), **kw) == D({1: 2})

    def test_keyfilter(self):
        D, kw = self.D, self.kw
        assert keyfilter(iseven, D({1: 2, 2: 3}), **kw) == D({2: 3})

    def test_itemfilter(self):
        D, kw = self.D, self.kw
        assert itemfilter(lambda item: iseven(item[0]), D({1: 2, 2: 3}), **kw) == D({2: 3})
        assert itemfilter(lambda item: iseven(item[1]), D({1: 2, 2: 3}), **kw) == D({1: 2})

    def test_assoc(self):
        D, kw = self.D, self.kw
        assert assoc(D({}), "a", 1, **kw) == D({"a": 1})
        assert assoc(D({"a": 1}), "a", 3, **kw) == D({"a": 3})
        assert assoc(D({"a": 1}), "b", 3, **kw) == D({"a": 1, "b": 3})

        # Verify immutability:
        d = D({'x': 1})
        oldd = d
        assoc(d, 'x', 2, **kw)
        assert d is oldd

    def test_dissoc(self):
        D, kw = self.D, self.kw
        assert dissoc(D({"a": 1}), "a", **kw) == D({})
        assert dissoc(D({"a": 1, "b": 2}), "a", **kw) == D({"b": 2})
        assert dissoc(D({"a": 1, "b": 2}), "b", **kw) == D({"a": 1})
        assert dissoc(D({"a": 1, "b": 2}), "a", "b", **kw) == D({})
        assert dissoc(D({"a": 1}), "a", **kw) == dissoc(dissoc(D({"a": 1}), "a", **kw), "a", **kw)

        # Verify immutability:
        d = D({'x': 1})
        oldd = d
        d2 = dissoc(d, 'x', **kw)
        assert d is oldd
        assert d2 is not oldd

    def test_assoc_in(self):
        D, kw = self.D, self.kw
        assert assoc_in(D({"a": 1}), ["a"], 2, **kw) == D({"a": 2})
        assert (assoc_in(D({"a": D({"b": 1})}), ["a", "b"], 2, **kw) ==
                D({"a": D({"b": 2})}))
        assert assoc_in(D({}), ["a", "b"], 1, **kw) == D({"a": D({"b": 1})})

        # Verify immutability:
        d = D({'x': 1})
        oldd = d
        d2 = assoc_in(d, ['x'], 2, **kw)
        assert d is oldd
        assert d2 is not oldd

    def test_update_in(self):
        D, kw = self.D, self.kw
        assert update_in(D({"a": 0}), ["a"], inc, **kw) == D({"a": 1})
        assert update_in(D({"a": 0, "b": 1}), ["b"], str, **kw) == D({"a": 0, "b": "1"})
        assert (update_in(D({"t": 1, "v": D({"a": 0})}), ["v", "a"], inc, **kw) ==
                D({"t": 1, "v": D({"a": 1})}))
        # Handle one missing key.
        assert update_in(D({}), ["z"], str, None, **kw) == D({"z": "None"})
        assert update_in(D({}), ["z"], inc, 0, **kw) == D({"z": 1})
        assert update_in(D({}), ["z"], lambda x: x+"ar", default="b", **kw) == D({"z": "bar"})
        # Same semantics as Clojure for multiple missing keys, ie. recursively
        # create nested empty dictionaries to the depth specified by the
        # keys with the innermost value set to f(default).
        assert update_in(D({}), [0, 1], inc, default=-1, **kw) == D({0: D({1: 0})})
        assert update_in(D({}), [0, 1], str, default=100, **kw) == D({0: D({1: "100"})})
        assert (update_in(D({"foo": "bar", 1: 50}), ["d", 1, 0], str, 20, **kw) ==
                D({"foo": "bar", 1: 50, "d": D({1: D({0: "20"})})}))
        # Verify immutability:
        d = D({'x': 1})
        oldd = d
        update_in(d, ['x'], inc, **kw)
        assert d is oldd

    def test_factory(self):
        D, kw = self.D, self.kw
        assert merge(defaultdict(int, D({1: 2})), D({2: 3})) == {1: 2, 2: 3}
        assert (merge(defaultdict(int, D({1: 2})), D({2: 3}),
                      factory=lambda: defaultdict(int)) ==
                defaultdict(int, D({1: 2, 2: 3})))
        assert not (merge(defaultdict(int, D({1: 2})), D({2: 3}),
                          factory=lambda: defaultdict(int)) == {1: 2, 2: 3})
        assert raises(TypeError, lambda: merge(D({1: 2}), D({2: 3}), factoryy=dict))


class defaultdict(_defaultdict):
    def __eq__(self, other):
        return (super().__eq__(other) and
                isinstance(other, _defaultdict) and
                self.default_factory == other.default_factory)


class TestDefaultDict(TestDict):
    """Test defaultdict as input and factory

    Class attributes:
        D: callable that inputs a dict and creates or returns a MutableMapping
        kw: kwargs dict to specify "factory" keyword (if applicable)
    """
    @staticmethod
    def D(dict_):
        return defaultdict(int, dict_)

    kw = {'factory': lambda: defaultdict(int)}


class CustomMapping:
    """Define methods of the MutableMapping protocol required by dicttoolz"""
    def __init__(self, *args, **kwargs):
        self._d = dict(*args, **kwargs)

    def __getitem__(self, key):
        return self._d[key]

    def __setitem__(self, key, val):
        self._d[key] = val

    def __delitem__(self, key):
        del self._d[key]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)

    def __contains__(self, key):
        return key in self._d

    def __eq__(self, other):
        return isinstance(other, CustomMapping) and self._d == other._d

    def __ne__(self, other):
        return not isinstance(other, CustomMapping) or self._d != other._d

    def keys(self):
        return self._d.keys()

    def values(self):
        return self._d.values()

    def items(self):
        return self._d.items()

    def update(self, *args, **kwargs):
        self._d.update(*args, **kwargs)

    # Unused methods that are part of the MutableMapping protocol
    #def get(self, key, *args):
    #    return self._d.get(key, *args)

    #def pop(self, key, *args):
    #    return self._d.pop(key, *args)

    #def popitem(self, key):
    #    return self._d.popitem()

    #def clear(self):
    #    self._d.clear()

    #def setdefault(self, key, *args):
    #    return self._d.setdefault(self, key, *args)


class TestCustomMapping(TestDict):
    """Test CustomMapping as input and factory

    Class attributes:
        D: callable that inputs a dict and creates or returns a MutableMapping
        kw: kwargs dict to specify "factory" keyword (if applicable)
    """
    D = CustomMapping
    kw = {'factory': lambda: CustomMapping()}


def test_environ():
    # See: https://github.com/pytoolz/cytoolz/issues/127
    assert keymap(identity, os.environ) == os.environ
    assert valmap(identity, os.environ) == os.environ
    assert itemmap(identity, os.environ) == os.environ


def test_merge_with_non_dict_mappings():
    class Foo(Mapping):
        def __init__(self, d):
            self.d = d

        def __iter__(self):
            return iter(self.d)

        def __getitem__(self, key):
            return self.d[key]

        def __len__(self):
            return len(self.d)

    d = Foo({1: 1})

    assert merge(d) is d or merge(d) == {1: 1}
    assert merge_with(sum, d) == {1: 1}


def test_merge_kwarg_error_names_the_offending_keyword():
    """The TypeError must name the keyword the caller actually passed."""
    try:
        merge({1: 2}, factoryy=dict)
        raise AssertionError("expected TypeError")
    except TypeError as e:
        assert "factoryy" in str(e)


def test_get_in_returns_default_for_a_missing_path():
    assert get_in(["a", "b"], {"a": {"b": 7}}) == 7
    assert get_in(["a", "z"], {"a": {"b": 7}}) is None
    assert get_in(["a", "z"], {"a": {"b": 7}}, default=-1) == -1
    assert get_in(["a", "b", "c"], {"a": {"b": 7}}, default=-1) == -1


def test_get_in_raises_when_no_default_is_set():
    assert raises(KeyError, lambda: get_in(["a", "z"], {"a": {"b": 7}}, no_default=True))
    assert raises(TypeError, lambda: get_in(["a", "b", "c"], {"a": {"b": 7}}, no_default=True))


def test_deep_merge_recurses_into_nested_mappings():
    result, report = deep_merge({'a': 1, 'b': {'x': 1}},
                                {'b': {'y': 2}, 'c': 3})
    assert result == {'a': 1, 'b': {'x': 1, 'y': 2}, 'c': 3}
    assert report == {'conflicts': [], 'cleared': []}


def test_deep_merge_missing_key_is_not_a_report():
    result, report = deep_merge({'a': 1}, {'b': 2})
    assert result == {'a': 1, 'b': 2}
    assert report == {'conflicts': [], 'cleared': []}


def test_deep_merge_equal_values_are_not_conflicts():
    result, report = deep_merge({'a': 1, 'b': {'x': 9}},
                                {'a': 1, 'b': {'x': 9}})
    assert result == {'a': 1, 'b': {'x': 9}}
    assert report['conflicts'] == []


def test_deep_merge_explicit_none_clears_the_field():
    result, report = deep_merge({'a': 1, 'b': 2}, {'b': None})
    assert result == {'a': 1}
    assert report['cleared'] == [('b',)]


def test_deep_merge_cleared_path_is_full_field_path():
    result, report = deep_merge({'b': {'x': 1, 'y': 2}},
                                {'b': {'y': None}})
    assert result == {'b': {'x': 1}}
    assert report['cleared'] == [('b', 'y')]


def test_deep_merge_last_source_wins_on_truthy_conflict():
    result, report = deep_merge({'a': 1}, {'a': 2})
    assert result == {'a': 2}
    assert report['conflicts'] == [(('a',), [1, 2], (0, 1))]


def test_deep_merge_conflict_record_keeps_source_order():
    sources = {'a': 'left'}, {'a': 'middle'}, {'a': 'right'}
    result, report = deep_merge(*sources)
    assert result == {'a': 'right'}
    path, values, sources_index = report['conflicts'][0]
    assert path == ('a',)
    assert values == ['left', 'middle', 'right']
    assert sources_index == (0, 1, 2)


def test_deep_merge_rules_select_by_full_field_path():
    rules = {('a',): min, ('b', 'nested',): max}
    result, report = deep_merge({'a': 1, 'b': {'nested': 3}},
                                {'a': 2, 'b': {'nested': 7}},
                                rules=rules)
    assert result == {'a': 1, 'b': {'nested': 7}}
    assert {entry[0] for entry in report['conflicts']} == {
        ('a',), ('b', 'nested')}


def test_deep_merge_rule_does_not_apply_to_other_paths():
    result, _ = deep_merge({'a': 1, 'b': 10}, {'a': 2, 'b': 20},
                           rules={('a',): lambda vals: vals[0]})
    assert result == {'a': 1, 'b': 20}


def test_deep_merge_shape_conflict_names_path_and_source_order():
    result, report = deep_merge({'b': {'x': 1}}, {'b': 2})
    assert result == {'b': 2}
    path, kinds, sources_index = report['conflicts'][0]
    assert path == ('b',)
    assert kinds == ['mapping', 'value']
    assert sources_index == (0, 1)


def test_deep_merge_retraction_beats_an_earlier_shape_conflict():
    result, report = deep_merge({'b': {'x': 1}}, {'b': None})
    assert result == {}
    assert report['cleared'] == [('b',)]
    assert report['conflicts'] == []


def test_deep_merge_does_not_mutate_inputs():
    first = {'a': 1, 'b': {'x': 1}}
    second = {'b': {'y': None}, 'c': 2}
    first_copy = {'a': 1, 'b': {'x': 1}}
    second_copy = {'b': {'y': None}, 'c': 2}
    deep_merge(first, second)
    assert first == first_copy
    assert second == second_copy


def test_deep_merge_accepts_a_single_iterable():
    sources = iter([{'a': 1}, {'a': 2}])
    result, report = deep_merge(sources)
    assert result == {'a': 2}
    assert report['conflicts'][0][0] == ('a',)


def test_deep_merge_reads_one_shot_mappings_once():
    class OneShotMapping(Mapping):
        def __init__(self, data):
            self._data = data
            self.iterations = 0

        def __getitem__(self, key):
            return self._data[key]

        def __len__(self):
            return len(self._data)

        def __iter__(self):
            self.iterations += 1
            return iter(self._data)

    source = OneShotMapping({'b': {'x': 1}})
    result, _ = deep_merge(source, {'b': {'y': 2}})
    assert result == {'b': {'x': 1, 'y': 2}}
    assert source.iterations == 1


def test_deep_merge_uses_factory_for_result_and_nested_maps():
    factory = lambda: defaultdict(int)
    result, _ = deep_merge({'b': {'x': 1}}, {'b': {'y': 2}},
                           factory=factory)
    assert result == defaultdict(int, {'b': defaultdict(
        int, {'x': 1, 'y': 2})})
    assert isinstance(result, defaultdict)
    assert isinstance(result['b'], defaultdict)


def test_deep_merge_rejects_unknown_kwargs():
    assert raises(TypeError, lambda: deep_merge({}, {}, factoryy=dict))


def test_deep_merge_is_curried_in_the_curried_namespace():
    from toolz.curried import deep_merge as curried_deep_merge

    partial = curried_deep_merge(rules={('a',): min})
    result, report = partial({'a': 1}, {'a': 2})
    assert result == {'a': 1}
    assert report['conflicts'][0][0] == ('a',)


def test_dissoc_agrees_on_both_sides_of_its_size_heuristic():
    """dissoc picks between two strategies on len(keys) vs len(d); both must agree."""
    d = {str(i): i for i in range(10)}
    assert dissoc(d, "1", "2") == {k: v for k, v in d.items() if k not in ("1", "2")}
    assert dissoc(d, *[str(i) for i in range(9)]) == {"9": 9}
    assert dissoc(d) == d
