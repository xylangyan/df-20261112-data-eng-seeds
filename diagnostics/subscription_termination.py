"""Replay graphql-core subscription termination behavior without a broker."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from graphql import (
    ExecutionResult,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    subscribe,
)


EVENTS = ("event-1", "event-2", "event-3")


def serialize_error(error: BaseException) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error)}


def serialize_result(result: ExecutionResult) -> dict[str, Any]:
    return {
        "kind": "result",
        "data": result.data,
        "errors": [serialize_error(error) for error in result.errors or []],
    }


def serialize_exception(error: BaseException) -> dict[str, Any]:
    return {"kind": "exception", **serialize_error(error)}


class SubscriptionProbe:
    """Drive one subscription and record caller-observable events."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.records: list[dict[str, Any]] = []
        self.schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query", {"noop": GraphQLField(GraphQLString)}
            ),
            subscription=GraphQLObjectType(
                "Subscription",
                {
                    "event": GraphQLField(
                        GraphQLString,
                        subscribe=self.source,
                        resolve=self.resolve_event,
                    )
                },
            ),
        )

    def record(self, action: str, **details: Any) -> None:
        self.records.append({"action": action, **details})

    async def source(self, _root: Any, _info: Any) -> AsyncIterator[str]:
        self.record("source_enter")
        try:
            for index, event in enumerate(EVENTS):
                self.record("source_yield", event=event)
                yield event
                if self.mode == "source_error" and index == 0:
                    error = RuntimeError("source failed after event-1")
                    self.record("source_raise", error=serialize_error(error))
                    raise error
            self.record("source_exhausted")
        finally:
            self.record("source_finally")

    def resolve_event(self, event: str, _info: Any) -> str:
        self.record("resolver_enter", event=event)
        if self.mode == "resolver_error" and event == "event-2":
            error = RuntimeError("resolver failed on event-2")
            self.record("resolver_raise", event=event, error=serialize_error(error))
            raise error
        return event.upper()

    async def run(self) -> dict[str, Any]:
        stream_or_result = subscribe(
            self.schema,
            parse("subscription { event }"),
        )
        if isinstance(stream_or_result, ExecutionResult):
            self.record(
                "subscribe_returned_error_result",
                result=serialize_result(stream_or_result),
            )
            return {"scenario": self.mode, "records": self.records}

        stream = stream_or_result
        self.record("subscribe_returned_stream")
        try:
            for pull in range(1, 5):
                self.record("caller_next", pull=pull)
                try:
                    result = await anext(stream)
                except StopAsyncIteration:
                    self.record("caller_observed", pull=pull, kind="stop")
                    break
                except Exception as error:
                    self.record(
                        "caller_observed",
                        pull=pull,
                        **serialize_exception(error),
                    )
                else:
                    self.record(
                        "caller_observed",
                        pull=pull,
                        **serialize_result(result),
                    )

                if self.mode == "caller_close" and pull == 2:
                    self.record("caller_close")
                    await stream.aclose()
        finally:
            await stream.aclose()
            self.record("diagnostic_cleanup_close")

        return {"scenario": self.mode, "records": self.records}


async def run_all() -> list[dict[str, Any]]:
    scenarios = []
    for mode in ("source_error", "resolver_error", "caller_close"):
        probe = SubscriptionProbe(mode)
        scenarios.append(await probe.run())
    return scenarios


def main() -> None:
    report = {
        "diagnostic": "graphql-core subscription termination",
        "events": list(EVENTS),
        "scenarios": asyncio.run(run_all()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
