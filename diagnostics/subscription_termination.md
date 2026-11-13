# Subscription Termination Diagnostic

This diagnostic uses an in-memory `GraphQLSchema` and three fixed source events
(`event-1`, `event-2`, `event-3`). It does not use an external broker or task-leak
warnings.

Run it with:

```sh
.venv/bin/python -B diagnostics/subscription_termination.py
```

The checked-in `subscription_termination_records.json` is the deterministic output
from that command. The source iterator has a `finally` block, and the caller closes
the response stream in cleanup so termination is recorded explicitly.

## Observed terminations

| Scenario | Caller sees | Source `finally` | Next event requested |
| --- | --- | --- | --- |
| Source generator raises after `event-1` | `RuntimeError` on pull 2; `StopAsyncIteration` on pull 3 | Yes, before the exception reaches the caller | No; pull 2 requested `__anext__` but no mapping occurred |
| Event resolver raises on `event-2` | `ExecutionResult` with `data={"event": None}` and a `GraphQLError`; pulls 3 and 4 continue | Yes, only when the source is exhausted | Yes; `event-3` is mapped and returned |
| Caller calls `stream.aclose()` after pull 2 | `StopAsyncIteration` on pull 3 | Yes, during `aclose()` | No; `event-3` is never requested |

## Safe continuation boundary

Continue calling `anext(stream)` only when it returns an `ExecutionResult`. That
includes results carrying field errors, such as the resolver failure above: GraphQL
field errors are per-event data and do not terminate the response stream.

If `anext(stream)` raises, the response stream itself has terminated. The source
iterator has already run its `finally` (or been closed), and the next call yields
`StopAsyncIteration`. That is the boundary for source-stream failures or explicit
consumer cancellation; do not treat them as a single bad event that can be skipped.
