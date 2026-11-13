import unittest

from cachetools import LRUCache

from . import CacheTestMixin


class LRUCacheTest(unittest.TestCase, CacheTestMixin):
    Cache = LRUCache

    def test_lru(self):
        cache = LRUCache[int, int](maxsize=2)

        cache[1] = 1
        cache[2] = 2
        cache[3] = 3

        self.assertEqual(len(cache), 2)
        self.assertEqual(cache[2], 2)
        self.assertEqual(cache[3], 3)
        self.assertNotIn(1, cache)

        cache[2]
        cache[4] = 4
        self.assertEqual(len(cache), 2)
        self.assertEqual(cache[2], 2)
        self.assertEqual(cache[4], 4)
        self.assertNotIn(3, cache)

        cache[5] = 5
        self.assertEqual(len(cache), 2)
        self.assertEqual(cache[4], 4)
        self.assertEqual(cache[5], 5)
        self.assertNotIn(2, cache)

    def test_lru_getsizeof(self):
        cache = LRUCache[int, int](maxsize=3, getsizeof=lambda x: x)

        cache[1] = 1
        cache[2] = 2

        self.assertEqual(len(cache), 2)
        self.assertEqual(cache[1], 1)
        self.assertEqual(cache[2], 2)

        cache[3] = 3

        self.assertEqual(len(cache), 1)
        self.assertEqual(cache[3], 3)
        self.assertNotIn(1, cache)
        self.assertNotIn(2, cache)

        with self.assertRaises(ValueError):
            cache[4] = 4
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache[3], 3)

    def test_lru_update_existing(self):
        cache = LRUCache[int, int | str](maxsize=2)

        cache[1] = 1
        cache[2] = 2
        cache[1] = "updated"
        cache[3] = 3

        self.assertEqual(cache[1], "updated")
        self.assertIn(3, cache)
        self.assertNotIn(2, cache)

    def test_lru_remeasure_grow_evicts_lru_items(self):
        # three weighted items; the middle item grows in place
        weights = {1: 1, 2: 2, 3: 3}
        cache = LRUCache[int, int](maxsize=10, getsizeof=weights.get)
        cache[1] = 1
        cache[2] = 2
        cache[3] = 3
        self.assertEqual([1, 2, 3], list(cache))
        self.assertEqual(6, cache.currsize)

        # grow the middle item to weight 9: the LRU item (1) goes first,
        # then the middle item itself is the next LRU candidate, leaving
        # only the most recently used item 3
        weights[2] = 9
        cache.remeasure(2)

        self.assertEqual([3], list(cache))
        self.assertEqual(3, cache.currsize)
        self.assertNotIn(1, cache)
        self.assertNotIn(2, cache)
        self.assertEqual(3, cache[3])

    def test_lru_remeasure_grow_respects_access_order(self):
        weights = {1: 1, 2: 2, 3: 3}
        cache = LRUCache[int, int](maxsize=10, getsizeof=weights.get)
        cache[1] = 1
        cache[2] = 2
        cache[3] = 3
        cache[1]  # make item 1 the most recently used
        self.assertEqual([2, 3, 1], list(cache._LRUCache__order))

        weights[2] = 9
        cache.remeasure(2)

        # item 2 itself is the LRU head and gets evicted; that alone
        # frees enough capacity, so the recently used item 1 and item 3
        # survive with their original weights
        self.assertEqual([1, 3], list(cache))
        self.assertEqual([3, 1], list(cache._LRUCache__order))
        self.assertEqual(4, cache.currsize)
        self.assertEqual(1, cache[1])
        self.assertEqual(3, cache[3])

    def test_lru_remeasure_does_not_change_order(self):
        weights = {1: 1, 2: 2, 3: 3}
        cache = LRUCache[int, int](maxsize=10, getsizeof=weights.get)
        cache[1] = 1
        cache[2] = 2
        cache[3] = 3
        cache[1]
        before = list(cache._LRUCache__order)

        weights[2] = 3
        cache.remeasure(2)

        self.assertEqual(before, list(cache._LRUCache__order))
        self.assertEqual(7, cache.currsize)

    def test_lru_remeasure_getsizeof_error_keeps_state(self):
        weights = {1: 1, 2: 2, 3: 3}
        fail = {"on": False}

        def getsizeof(key):
            if fail["on"] and key == 2:
                raise RuntimeError("boom")
            return weights[key]

        cache = LRUCache[int, int](maxsize=10, getsizeof=getsizeof)
        cache[1] = 1
        cache[2] = 2
        cache[3] = 3
        snapshot_items = list(cache)
        snapshot_size = cache.currsize
        fail["on"] = True

        with self.assertRaises(RuntimeError):
            cache.remeasure(2)

        # nothing is evicted and the accounting is not touched
        self.assertEqual(snapshot_items, list(cache))
        self.assertEqual(snapshot_size, cache.currsize)
        self.assertEqual({1, 2, 3}, set(cache))

    def test_lru_clear(self):
        cache = LRUCache[int, int](maxsize=2)

        cache[1] = 1
        cache[2] = 2
        cache.clear()

        self.assertEqual(0, len(cache))
        self.assertEqual(0, cache.currsize)

        # verify LRU order is reset after clear
        cache[3] = 3
        cache[4] = 4
        cache[3]  # access 3 to make it most recently used
        cache[5] = 5  # should evict 4 (least recently used)

        self.assertEqual(2, len(cache))
        self.assertIn(3, cache)
        self.assertIn(5, cache)
        self.assertNotIn(4, cache)
