import math
import unittest

from cachetools import RemovalReason, TTLCache

from . import CacheTestMixin


class Timer:
    def __init__(self, auto=False):
        self.auto = auto
        self.time = 0

    def __call__(self):
        if self.auto:
            self.time += 1
        return self.time

    def tick(self):
        self.time += 1


class TTLTestCache(TTLCache):
    def __init__(self, maxsize, ttl=math.inf, **kwargs):
        TTLCache.__init__(self, maxsize, ttl=ttl, timer=Timer(), **kwargs)


class TTLCacheTest(unittest.TestCase, CacheTestMixin):
    Cache = TTLTestCache

    def test_ttl(self):
        cache = TTLCache[int, int, int](maxsize=2, ttl=2, timer=Timer())
        self.assertEqual(0, cache.timer())
        self.assertEqual(2, cache.ttl)

        cache[1] = 1
        self.assertEqual(1, cache[1])
        self.assertEqual(1, len(cache))
        self.assertEqual({1}, set(cache))

        cache.timer.tick()
        self.assertEqual(1, cache[1])
        self.assertEqual(1, len(cache))
        self.assertEqual({1}, set(cache))

        cache[2] = 2
        self.assertEqual(1, cache[1])
        self.assertEqual(2, cache[2])
        self.assertEqual(2, len(cache))
        self.assertEqual({1, 2}, set(cache))

        cache.timer.tick()
        self.assertNotIn(1, cache)
        self.assertEqual(2, cache[2])
        self.assertEqual(1, len(cache))
        self.assertEqual({2}, set(cache))

        cache[3] = 3
        self.assertNotIn(1, cache)
        self.assertEqual(2, cache[2])
        self.assertEqual(3, cache[3])
        self.assertEqual(2, len(cache))
        self.assertEqual({2, 3}, set(cache))

        cache.timer.tick()
        self.assertNotIn(1, cache)
        self.assertNotIn(2, cache)
        self.assertEqual(3, cache[3])
        self.assertEqual(1, len(cache))
        self.assertEqual({3}, set(cache))

        cache.timer.tick()
        self.assertNotIn(1, cache)
        self.assertNotIn(2, cache)
        self.assertNotIn(3, cache)

        with self.assertRaises(KeyError):
            del cache[1]
        with self.assertRaises(KeyError):
            cache.pop(2)
        with self.assertRaises(KeyError):
            del cache[3]

        self.assertEqual(0, len(cache))
        self.assertEqual(set(), set(cache))

    def test_ttl_timer(self):
        cache = TTLCache[int, int, int](maxsize=2, ttl=2, timer=Timer())
        self.assertEqual(cache.timer.time, 0)
        self.assertFalse(cache.timer.auto)

        cache[1] = 1
        cache.timer.tick()
        self.assertEqual(cache.timer.time, 1)
        self.assertEqual(1, cache[1])

        cache.timer.tick()
        self.assertEqual(cache.timer.time, 2)
        self.assertNotIn(1, cache)

    def test_ttl_lru(self):
        cache = TTLCache[int, int, int](maxsize=2, ttl=1, timer=Timer())

        cache[1] = 1
        cache[2] = 2
        cache[3] = 3

        self.assertEqual(len(cache), 2)
        self.assertNotIn(1, cache)
        self.assertEqual(cache[2], 2)
        self.assertEqual(cache[3], 3)

        cache[2]
        cache[4] = 4
        self.assertEqual(len(cache), 2)
        self.assertNotIn(1, cache)
        self.assertEqual(cache[2], 2)
        self.assertNotIn(3, cache)
        self.assertEqual(cache[4], 4)

        cache[5] = 5
        self.assertEqual(len(cache), 2)
        self.assertNotIn(1, cache)
        self.assertNotIn(2, cache)
        self.assertNotIn(3, cache)
        self.assertEqual(cache[4], 4)
        self.assertEqual(cache[5], 5)

    def test_ttl_expire(self):
        cache = TTLCache[int, int, int](maxsize=3, ttl=3, timer=Timer())
        with cache.timer as time:
            self.assertEqual(time, cache.timer())
        self.assertEqual(3, cache.ttl)

        cache[1] = 1
        cache.timer.tick()
        cache[2] = 2
        cache.timer.tick()
        cache[3] = 3
        self.assertEqual(2, cache.timer())

        self.assertEqual({1, 2, 3}, set(cache))
        self.assertEqual(3, len(cache))
        self.assertEqual(1, cache[1])
        self.assertEqual(2, cache[2])
        self.assertEqual(3, cache[3])

        items = cache.expire()
        self.assertEqual(set(), set(items))
        self.assertEqual({1, 2, 3}, set(cache))
        self.assertEqual(3, len(cache))
        self.assertEqual(1, cache[1])
        self.assertEqual(2, cache[2])
        self.assertEqual(3, cache[3])

        items = cache.expire(3)
        self.assertEqual({(1, 1)}, set(items))
        self.assertEqual({2, 3}, set(cache))
        self.assertEqual(2, len(cache))
        self.assertNotIn(1, cache)
        self.assertEqual(2, cache[2])
        self.assertEqual(3, cache[3])

        items = cache.expire(4)
        self.assertEqual({(2, 2)}, set(items))
        self.assertEqual({3}, set(cache))
        self.assertEqual(1, len(cache))
        self.assertNotIn(1, cache)
        self.assertNotIn(2, cache)
        self.assertEqual(3, cache[3])

        items = cache.expire(5)
        self.assertEqual({(3, 3)}, set(items))
        self.assertEqual(set(), set(cache))
        self.assertEqual(0, len(cache))
        self.assertNotIn(1, cache)
        self.assertNotIn(2, cache)
        self.assertNotIn(3, cache)

    def test_ttl_iter_expired(self):
        cache = TTLCache[int, int, int](maxsize=2, ttl=2, timer=Timer())
        cache[1] = 1
        cache.timer.tick()
        cache[2] = 2
        cache.timer.tick()
        # a bare for loop skips expired items without removing them
        self.assertEqual([2], [key for key in cache])
        self.assertEqual({(1, 1)}, set(cache.expire()))
        self.assertEqual([2], [key for key in cache])

    def test_ttl_atomic(self):
        cache = TTLCache[int, int | None, int](maxsize=1, ttl=2, timer=Timer(auto=True))
        cache[1] = 1
        self.assertEqual(1, cache[1])
        cache[1] = 1
        self.assertEqual(1, cache.get(1))
        cache[1] = 1
        self.assertEqual(1, cache.pop(1))
        cache[1] = 1
        self.assertEqual(1, cache.setdefault(1))  # implicit default=None
        cache[1] = 1
        cache.clear()
        self.assertEqual(0, len(cache))

    def test_ttl_tuple_key(self):
        cache = TTLCache[tuple[int, ...], int, int](maxsize=1, ttl=1, timer=Timer())
        self.assertEqual(1, cache.ttl)

        cache[(1, 2, 3)] = 42
        self.assertEqual(42, cache[(1, 2, 3)])
        cache.timer.tick()
        with self.assertRaises(KeyError):
            cache[(1, 2, 3)]
        self.assertNotIn((1, 2, 3), cache)

    def test_ttl_datetime(self):
        from datetime import datetime, timedelta

        cache = TTLCache[int, int, datetime](
            maxsize=1, ttl=timedelta(days=1), timer=datetime.now
        )

        cache[1] = 1
        self.assertEqual(1, len(cache))
        items = cache.expire(datetime.now())
        self.assertEqual([], list(items))
        self.assertEqual(1, len(cache))
        items = cache.expire(datetime.now() + timedelta(days=1))
        self.assertEqual([(1, 1)], list(items))
        self.assertEqual(0, len(cache))

    def test_ttl_datetime_overflow(self):
        from datetime import datetime, timedelta

        cache = TTLCache[str, int, datetime](
            maxsize=1, ttl=timedelta(days=1), timer=lambda: datetime.max
        )

        with self.assertRaises(OverflowError):
            cache["overflow"] = 1

        self.assertNotIn("overflow", cache)
        self.assertEqual(0, len(cache))
        self.assertEqual(0, cache.currsize)
        self.assertEqual([], list(cache))
        self.assertEqual([], cache.expire())

    def test_ttl_clear(self):
        cache = TTLCache[int, int, int](maxsize=2, ttl=2, timer=Timer())

        cache[1] = 1
        cache[2] = 2
        cache.clear()

        self.assertEqual(0, len(cache))
        self.assertEqual(0, cache.currsize)

        # verify LRU eviction order is reset after clear
        cache[3] = 3
        cache[4] = 4
        cache[3]  # access 3 to make it most recently used
        cache[5] = 5  # should evict 4 (least recently used)

        self.assertEqual(2, len(cache))
        self.assertIn(3, cache)
        self.assertIn(5, cache)
        self.assertNotIn(4, cache)

        # verify TTL expiry still works after clear
        cache[42] = 42
        cache.timer.tick()
        cache.timer.tick()
        cache.timer.tick()  # past TTL
        self.assertNotIn(42, cache)

    def test_ttl_eviction_notification(self):
        # an expired item, a live item and a new value compete for capacity
        record = []
        cache = TTLCache[int, str, int](
            maxsize=2,
            ttl=2,
            timer=Timer(),
            getsizeof=lambda value: 2 if value == "incoming" else 1,
            on_evict=lambda key, value, reason: record.append((key, value, reason)),
        )
        cache[1] = "expired"  # expires at t=2
        cache.timer.tick()
        cache[2] = "active"  # expires at t=3
        cache.timer.tick()  # t=2: key 1 is stale but still resident
        self.assertEqual([], record)

        cache[3] = "incoming"  # size 2: stale key leaves, live key must go
        self.assertEqual(
            [
                (1, "expired", RemovalReason.EXPIRED),
                (2, "active", RemovalReason.EVICTED),
            ],
            record,
        )
        self.assertEqual([3], list(cache))
        self.assertEqual(2, cache.currsize)

    def test_ttl_eviction_reasons(self):
        record = []
        cache = TTLCache[int, int, int](
            maxsize=2,
            ttl=2,
            timer=Timer(),
            on_evict=lambda key, value, reason: record.append((key, value, reason)),
        )

        cache[1] = 1
        del cache[1]
        self.assertEqual([(1, 1, RemovalReason.DELETED)], record)

        record.clear()
        cache[1] = 1
        cache[2] = 2
        cache[3] = 3
        self.assertEqual([(1, 1, RemovalReason.EVICTED)], record)
        self.assertEqual({2, 3}, set(cache))

        cache.timer.tick()
        cache.timer.tick()
        record.clear()
        cache[4] = 4  # lazily expires keys 2 and 3 before inserting
        self.assertEqual(
            [
                (2, 2, RemovalReason.EXPIRED),
                (3, 3, RemovalReason.EXPIRED),
            ],
            record,
        )
        self.assertEqual([4], list(cache))

    def test_ttl_clear_notification(self):
        record = []
        cache = TTLCache[int, int, int](
            maxsize=4,
            ttl=10,
            timer=Timer(),
            on_evict=lambda key, value, reason: record.append((key, value, reason)),
        )
        cache[1] = 1
        cache[2] = 2
        cache[3] = 3
        order_before = list(cache)
        cache.clear()
        self.assertEqual(
            [
                (1, 1, RemovalReason.CLEARED),
                (2, 2, RemovalReason.CLEARED),
                (3, 3, RemovalReason.CLEARED),
            ],
            record,
        )
        self.assertEqual(order_before, [key for key, _, _ in record])
        self.assertEqual(0, len(cache))

        # an empty clear sends no notifications
        record.clear()
        cache.clear()
        self.assertEqual([], record)

    def test_ttl_eviction_failed_insert(self):
        record = []
        cache = TTLCache[int, str, int](
            maxsize=2,
            ttl=10,
            timer=Timer(),
            getsizeof=len,
            on_evict=lambda key, value, reason: record.append((key, value, reason)),
        )
        cache[1] = "a"
        cache[2] = "b"
        with self.assertRaises(ValueError):
            cache[3] = "too large"
        # the rejected value never counts as a successful removal
        self.assertEqual([], record)
        self.assertEqual({1, 2}, set(cache))

    def test_ttl_eviction_callback_exception(self):
        def callback(key, value, reason):
            raise RuntimeError("callback failed")

        # the state change is committed before the callback is invoked
        cache = TTLCache[int, int, int](
            maxsize=1, ttl=10, timer=Timer(), on_evict=callback
        )
        cache[1] = 1
        with self.assertRaises(RuntimeError):
            cache[2] = 2
        self.assertEqual([], list(cache))
        cache[3] = 3  # the cache remains usable afterwards
        self.assertEqual([3], list(cache))

        cache = TTLCache[int, int, int](
            maxsize=4, ttl=1, timer=Timer(), on_evict=callback
        )
        cache[1] = 1
        cache.timer.tick()
        cache.timer.tick()
        with self.assertRaises(RuntimeError):
            cache[2] = 2
        self.assertEqual([], list(cache))

        cache = TTLCache[int, int, int](
            maxsize=4, ttl=10, timer=Timer(), on_evict=callback
        )
        cache[1] = 1
        with self.assertRaises(RuntimeError):
            cache.clear()
        self.assertEqual(0, len(cache))

    def test_ttl_eviction_default(self):
        # without on_evict, behavior is unchanged
        cache = TTLTestCache(maxsize=1)
        cache[1] = 1
        cache[2] = 2
        self.assertEqual([2], list(cache))

    def test_ttl_default_timer_stubs(self):
        # type stubs must infer key and value types with the default timer
        cache: TTLCache[str, int] = TTLCache(maxsize=2, ttl=math.inf)

        cache["a"] = 1
        self.assertEqual(1, cache["a"])
        self.assertEqual(1, len(cache))
        self.assertIn("a", cache)

        sized: TTLCache[str, str] = TTLCache(maxsize=10, ttl=math.inf, getsizeof=len)

        sized["abc"] = "abc"
        self.assertEqual("abc", sized["abc"])
        self.assertEqual(3, sized.currsize)

    def test_ttl_on_evict_stubs(self):
        # type stubs must accept the typed on_evict callback
        def on_evict(key: int, value: int, reason: RemovalReason) -> None:
            self.assertIsInstance(reason, RemovalReason)

        cache: TTLCache[int, int] = TTLCache(maxsize=2, ttl=60, on_evict=on_evict)
        cache[1] = 1

        from datetime import datetime, timedelta

        timed: TTLCache[int, int, datetime] = TTLCache(
            maxsize=2,
            ttl=timedelta(hours=1),
            timer=datetime.now,
            on_evict=on_evict,
        )
        timed[1] = 1
        self.assertEqual(1, timed[1])
