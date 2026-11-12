from toolz import first, identity, countby, partitionby, partitionby_iter
from toolz.utils import raises, no_default


def iseven(x):
    return x % 2 == 0


def test_countby():
    assert countby(iseven, [1, 2, 3]) == {True: 1, False: 2}
    assert countby(len, ['cat', 'dog', 'mouse']) == {3: 2, 5: 1}
    assert countby(0, ('ab', 'ac', 'bc')) == {'a': 2, 'b': 1}


def test_partitionby():
    assert list(partitionby(identity, [])) == []

    vowels = "aeiou"
    assert (list(partitionby(vowels.__contains__, "abcdefghi")) ==
            [("a",), ("b", "c", "d"), ("e",), ("f", "g", "h"), ("i",)])

    assert (list(map(first,
                     partitionby(identity,
                                 [1, 1, 1, 2, 3, 3, 2, 2, 3]))) ==
            [1, 2, 3, 2, 3])

    assert ''.join(map(first,
                       partitionby(identity, "Khhhaaaaannnnn!!!!"))) == 'Khan!'


def test_partitionby_iter():
    assert list(partitionby_iter(identity, [])) == []

    groups = partitionby_iter(identity, [1, 1, 2, 3, 3, 2])
    first_group = next(groups)
    assert first_group.key == 1
    assert first_group.count == 0
    assert list(first_group) == [1, 1]
    assert first_group.count == 2
    assert first_group.summary == (1, 2, no_default)

    second_group = next(groups)
    assert second_group.key == 2
    assert list(second_group) == [2]
    third_group = next(groups)
    assert third_group.key == 3
    assert next(third_group) == 3
    fourth_group = next(groups)
    assert fourth_group.key == 2
    assert list(fourth_group) == [2]

    # A repeated key starts a new partition, and an inactive partition
    # cannot silently consume the next group's input.
    assert raises(RuntimeError, lambda: next(first_group))
    assert raises(RuntimeError, lambda: next(second_group))


def test_partitionby_iter_skip_and_summary():
    consumed = []

    def source():
        for item in [('a', 1), ('a', 2), ('b', 3), ('b', 4), ('c', 5)]:
            consumed.append(item)
            yield item

    groups = partitionby_iter(first, source(), lambda total, x: total + x[1],
                               0)
    first_group = next(groups)
    assert first_group.key == 'a'
    assert next(first_group) == ('a', 1)
    assert first_group.count == 1
    assert raises(RuntimeError, lambda: first_group.summary)

    summary = first_group.skip()
    # Skipping still counts the records, but does not run the reducer.
    assert summary == ('a', 2, no_default)
    # Detecting the end of a group pulls the first item of the next group
    # into the partition iterator's one-item boundary buffer.
    assert consumed == [('a', 1), ('a', 2), ('b', 3)]

    second_group = next(groups)
    assert second_group.key == 'b'
    # Advancing without consuming drains the current partition only.
    third_group = next(groups)
    assert third_group.key == 'c'
    assert consumed == [('a', 1), ('a', 2), ('b', 3), ('b', 4), ('c', 5)]
    assert second_group.summary == ('b', 2, no_default)
    assert raises(RuntimeError, lambda: next(second_group))
    assert list(third_group) == [('c', 5)]
    assert third_group.summary == ('c', 1, 5)


def test_partitionby_iter_reducer_error():
    consumed = []

    def source():
        for item in [1, 1, 2, 2, 3, 3, 4]:
            consumed.append(item)
            yield item

    def reducer(total, x):
        if x == 3:
            raise ValueError('bad record')
        return total + x

    groups = partitionby_iter(identity, source(), reducer, 0)
    first_group = next(groups)
    assert list(first_group) == [1, 1]
    assert first_group.summary == (1, 2, 2)

    second_group = next(groups)
    assert next(second_group) == 2
    with_error = next(groups)
    assert with_error.key == 3
    assert raises(ValueError, lambda: next(with_error))
    assert consumed == [1, 1, 2, 2, 3]
    assert with_error.count == 1
    assert raises(RuntimeError, lambda: with_error.summary)
    assert raises(RuntimeError, lambda: next(with_error))

    # The failed partition can still be drained without rerunning the reducer.
    next_group = next(groups)
    assert next_group.key == 4
    assert consumed == [1, 1, 2, 2, 3, 3, 4]
    assert raises(RuntimeError, lambda: with_error.summary)


def test_partitionby_iter_reducer_without_init():
    group = next(partitionby_iter(identity, [1, 1, 1],
                                  lambda total, x: total + x))
    assert list(group) == [1, 1, 1]
    assert group.summary == (1, 3, 3)

    group = next(partitionby_iter(identity, [1, 1],
                                  lambda total, x: total + x, lambda: 10))
    assert list(group) == [1, 1]
    assert group.summary == (1, 2, 12)


def test_partitionby_iter_evaluates_key_once():
    keys = []

    def key(item):
        keys.append(item)
        return item

    for group in partitionby_iter(key, [1, 1, 2, 2, 3]):
        list(group)

    assert keys == [1, 1, 2, 2, 3]


def test_partitionby_iter_is_not_greedy():
    def source():
        yield 1
        yield 1
        raise AssertionError('read too far')

    group = next(partitionby_iter(identity, source()))
    assert next(group) == 1
    assert next(group) == 1
    assert raises(AssertionError, lambda: next(group))
