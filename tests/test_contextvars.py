# SPDX-License-Identifier: MIT OR Apache-2.0
# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the MIT License.  See the LICENSE file in the root of this
# repository for complete details.

import asyncio
import inspect
import logging
import secrets
import threading

import pytest

import structlog

from structlog import make_filtering_bound_logger
from structlog.contextvars import (
    _ASYNC_CALLING_THREAD,
    _CONTEXT_VARS,
    bind_contextvars,
    bound_contextvars,
    clear_contextvars,
    get_contextvars,
    get_merged_contextvars,
    merge_contextvars,
    reset_contextvars,
    unbind_contextvars,
)
from structlog.processors import CallsiteParameter, CallsiteParameterAdder
from structlog.stdlib import BoundLogger as StdlibBoundLogger
from structlog.testing import CapturingLogger


@pytest.fixture(autouse=True)
def _clear_contextvars():
    """
    Make sure all tests start with a clean slate.
    """
    clear_contextvars()


class TestContextvars:
    async def test_bind(self):
        """
        Binding a variable causes it to be included in the result of
        merge_contextvars.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            bind_contextvars(a=1)
            return merge_contextvars(None, None, {"b": 2})

        assert {"a": 1, "b": 2} == await event_loop.create_task(coro())

    async def test_multiple_binds(self):
        """
        Multiple calls to bind_contextvars accumulate values instead of
        replacing them. But they override redefined ones.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            bind_contextvars(a=1, c=3)
            bind_contextvars(c=333, d=4)
            return merge_contextvars(None, None, {"b": 2})

        assert {
            "a": 1,
            "b": 2,
            "c": 333,
            "d": 4,
        } == await event_loop.create_task(coro())

    async def test_reset(self):
        """
        reset_contextvars allows resetting contexvars to
        previously-set values.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            bind_contextvars(a=1)

            assert {"a": 1} == get_contextvars()

            await event_loop.create_task(nested_coro())

        async def nested_coro():
            tokens = bind_contextvars(a=2, b=3)

            assert {"a": 2, "b": 3} == get_contextvars()

            reset_contextvars(**tokens)

            assert {"a": 1} == get_contextvars()

        await event_loop.create_task(coro())

    async def test_nested_async_bind(self):
        """
        Context is passed correctly between "nested" concurrent operations.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            bind_contextvars(a=1)
            return await event_loop.create_task(nested_coro())

        async def nested_coro():
            bind_contextvars(c=3)
            return merge_contextvars(None, None, {"b": 2})

        assert {"a": 1, "b": 2, "c": 3} == await event_loop.create_task(coro())

    async def test_merge_works_without_bind(self):
        """
        merge_contextvars returns values as normal even when there has
        been no previous calls to bind_contextvars.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            return merge_contextvars(None, None, {"b": 2})

        assert {"b": 2} == await event_loop.create_task(coro())

    async def test_merge_overrides_bind(self):
        """
        Variables included in merge_contextvars override previously
        bound variables.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            bind_contextvars(a=1)
            return merge_contextvars(None, None, {"a": 111, "b": 2})

        assert {"a": 111, "b": 2} == await event_loop.create_task(coro())

    async def test_clear(self):
        """
        The context-local context can be cleared, causing any previously bound
        variables to not be included in merge_contextvars's result.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            bind_contextvars(a=1)
            clear_contextvars()
            return merge_contextvars(None, None, {"b": 2})

        assert {"b": 2} == await event_loop.create_task(coro())

    async def test_clear_without_bind(self):
        """
        The context-local context can be cleared, causing any previously bound
        variables to not be included in merge_contextvars's result.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            clear_contextvars()
            return merge_contextvars(None, None, {})

        assert {} == await event_loop.create_task(coro())

    async def test_unbind(self):
        """
        Unbinding a previously bound variable causes it to be removed from the
        result of merge_contextvars.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            bind_contextvars(a=1)
            unbind_contextvars("a")
            return merge_contextvars(None, None, {"b": 2})

        assert {"b": 2} == await event_loop.create_task(coro())

    async def test_unbind_not_bound(self):
        """
        Unbinding a not bound variable causes doesn't raise an exception.
        """
        event_loop = asyncio.get_running_loop()

        async def coro():
            # Since unbinding means "setting to Ellipsis", we have to make
            # some effort to ensure that the ContextVar never existed.
            unbind_contextvars("a" + secrets.token_hex())

            return merge_contextvars(None, None, {"b": 2})

        assert {"b": 2} == await event_loop.create_task(coro())

    async def test_parallel_binds(self):
        """
        Binding a variable causes it to be included in the result of
        merge_contextvars.
        """
        event_loop = asyncio.get_running_loop()
        coro1_bind = asyncio.Event()
        coro2_bind = asyncio.Event()

        bind_contextvars(c=3)

        async def coro1():
            bind_contextvars(a=1)

            coro1_bind.set()
            await coro2_bind.wait()

            return merge_contextvars(None, None, {"b": 2})

        async def coro2():
            bind_contextvars(a=2)

            await coro1_bind.wait()
            coro2_bind.set()

            return merge_contextvars(None, None, {"b": 2})

        coro1_task = event_loop.create_task(coro1())
        coro2_task = event_loop.create_task(coro2())

        assert {"a": 1, "b": 2, "c": 3} == await coro1_task
        assert {"a": 2, "b": 2, "c": 3} == await coro2_task

    def test_get_only_gets_structlog_without_deleted(self):
        """
        get_contextvars returns only the structlog-specific key-values with
        the prefix removed. Deleted keys (= Ellipsis) are ignored.
        """
        bind_contextvars(a=1, b=2)
        unbind_contextvars("b")
        _CONTEXT_VARS["foo"] = "bar"

        assert {"a": 1} == get_contextvars()

    def test_get_merged_merges_context(self):
        """
        get_merged_contextvars merges a bound context into the copy.
        """
        bind_contextvars(x=1)
        log = structlog.get_logger().bind(y=2)

        assert {"x": 1, "y": 2} == get_merged_contextvars(log)


class TestBoundContextvars:
    def test_cleanup(self):
        """
        Bindings are cleaned up
        """
        with bound_contextvars(x=42, y="foo"):
            assert {"x": 42, "y": "foo"} == get_contextvars()

        assert {} == get_contextvars()

    def test_cleanup_conflict(self):
        """
        Overwritten keys are restored after the clean up
        """
        bind_contextvars(x="original", z="unrelated")
        with bound_contextvars(x=42, y="foo"):
            assert {"x": 42, "y": "foo", "z": "unrelated"} == get_contextvars()

        assert {"x": "original", "z": "unrelated"} == get_contextvars()

    def test_preserve_independent_bind(self):
        """
        New bindings inside bound_contextvars are preserved after the clean up
        """
        with bound_contextvars(x=42):
            bind_contextvars(y="foo")
            assert {"x": 42, "y": "foo"} == get_contextvars()

        assert {"y": "foo"} == get_contextvars()

    def test_nesting_works(self):
        """
        bound_contextvars binds and unbinds even when nested
        """
        with bound_contextvars(l1=1):
            assert {"l1": 1} == get_contextvars()

            with bound_contextvars(l2=2):
                assert {"l1": 1, "l2": 2} == get_contextvars()

            assert {"l1": 1} == get_contextvars()

        assert {} == get_contextvars()

    def test_as_decorator(self):
        """
        bound_contextvars can be used as a decorator and it preserves the
        name, signature and documentation of the wrapped function.
        """

        @bound_contextvars(x=42)
        def wrapped(arg1):
            """Wrapped documentation"""
            bind_contextvars(y=arg1)
            assert {"x": 42, "y": arg1} == get_contextvars()

        wrapped(23)

        assert "wrapped" == wrapped.__name__
        assert "(arg1)" == str(inspect.signature(wrapped))
        assert "Wrapped documentation" == wrapped.__doc__


class TestAsyncContextAttribution:
    """
    Async log entries must be attributed to the context that was active at
    *call time*, even though the processor chain runs on an executor thread.
    """

    @staticmethod
    def _build_logger(flavor, sink):
        """
        A logger of *flavor* ("stdlib" or "native") whose async entries merge
        the contextvars context and end in the shared capturing *sink*.
        """
        processors = [merge_contextvars]

        if flavor == "stdlib":
            return StdlibBoundLogger(sink, processors, {})

        return make_filtering_bound_logger(logging.NOTSET)(
            sink, processors, {}
        )

    @pytest.fixture(params=["stdlib", "native"])
    def flavor(self, request):
        return request.param

    async def test_interleaved_groups_keep_their_partition(self, flavor):
        """
        Two source groups logging through a common barrier never swap or lose
        their ``partition_id``; records are matched by their message.
        """
        sink = CapturingLogger()
        log = self._build_logger(flavor, sink)
        barrier = asyncio.Barrier(2)

        async def collect(group):
            bind_contextvars(partition_id=group)
            await barrier.wait()
            await log.ainfo(f"{group}-one")
            await log.ainfo(f"{group}-two")

        await asyncio.gather(collect("A"), collect("B"))

        by_event = {
            call.kwargs["event"]: call.kwargs
            for call in sink.calls
        }

        assert 4 == len(sink.calls)
        assert "A" == by_event["A-one"]["partition_id"]
        assert "A" == by_event["A-two"]["partition_id"]
        assert "B" == by_event["B-one"]["partition_id"]
        assert "B" == by_event["B-two"]["partition_id"]

    async def test_processor_thread_reads_call_time_context(self, flavor):
        """
        The executor-thread processor sees the calling context, including the
        captured calling thread, rather than the executor's own thread.
        """
        sink = CapturingLogger()
        adder = CallsiteParameterAdder(
            [
                CallsiteParameter.THREAD,
                CallsiteParameter.THREAD_NAME,
            ]
        )

        if flavor == "stdlib":
            log = StdlibBoundLogger(sink, [merge_contextvars, adder], {})
        else:
            log = make_filtering_bound_logger(logging.NOTSET)(
                sink, [merge_contextvars, adder], {}
            )

        calling_ident = threading.get_ident()
        calling_name = threading.current_thread().name
        bind_contextvars(partition_id="A")

        await log.ainfo("thread-attributed")

        (call,) = sink.calls
        assert calling_ident == call.kwargs["thread"]
        assert calling_name == call.kwargs["thread_name"]
        assert "A" == call.kwargs["partition_id"]
        # The async entry point must not leak the captured metadata into the
        # calling context once it is done.
        assert _ASYNC_CALLING_THREAD.get(None) is None

    async def test_nested_override_raises_restores_outer_id(self, flavor):
        """
        A temporary nested binding that raises still restores the outer
        partition ID, and neither the temporary nor the outer value leaks
        into a sibling task.
        """
        sink = CapturingLogger()
        log = self._build_logger(flavor, sink)
        barrier = asyncio.Barrier(2)

        async def with_nested_failure():
            bind_contextvars(partition_id="A")
            await barrier.wait()
            try:
                with bound_contextvars(partition_id="A-nested"):
                    await log.ainfo("A-nested-before-error")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            await log.ainfo("A-restored")

        async def sibling():
            bind_contextvars(partition_id="B")
            await barrier.wait()
            await log.ainfo("B-sibling")

        await asyncio.gather(with_nested_failure(), sibling())

        by_event = {
            call.kwargs["event"]: call.kwargs
            for call in sink.calls
        }

        assert "A-nested" == by_event["A-nested-before-error"][
            "partition_id"
        ]
        assert "A" == by_event["A-restored"]["partition_id"]
        assert "B" == by_event["B-sibling"]["partition_id"]
        assert {} == get_contextvars()

    async def test_cancellation_restores_outer_binding(self, flavor):
        """
        Cancelling a task inside a nested binding restores the outer value
        for the next log call made from the parent context.
        """
        sink = CapturingLogger()
        log = self._build_logger(flavor, sink)
        started = asyncio.Event()
        release = asyncio.Event()

        async def child():
            with bound_contextvars(partition_id="child"):
                started.set()
                await release.wait()

        async def parent():
            bind_contextvars(partition_id="parent")
            task = asyncio.create_task(child())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await log.ainfo("after-cancellation")

        await parent()

        (call,) = sink.calls
        assert "after-cancellation" == call.kwargs["event"]
        assert "parent" == call.kwargs["partition_id"]

    async def test_unbound_call_still_logs(self, flavor):
        """
        Without any bound partition ID the async entry still writes; the
        missing key simply stays absent from the event dict.
        """
        sink = CapturingLogger()
        log = self._build_logger(flavor, sink)

        await log.ainfo("no-binding")

        (call,) = sink.calls
        assert "no-binding" == call.kwargs["event"]
        assert "partition_id" not in call.kwargs
