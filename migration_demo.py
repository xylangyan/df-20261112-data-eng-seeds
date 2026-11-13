"""
Phased ``job`` -> ``run_id`` field migration demo.

The same FieldMigrator configuration is exercised through three input
shapes (old, mixed, new) and through both entry points (a plain
structlog chain and ProcessorFormatter). Every converted output is then
pushed through the *same* configuration a second time to prove the
migration markers and fields are stable.
"""

from __future__ import annotations

import json
import logging

from io import StringIO

import structlog

from structlog.processors import FieldMigrator, JSONRenderer
from structlog.stdlib import (
    ExtraAdder,
    ProcessorFormatter,
)
from structlog.testing import CapturingLoggerFactory

INPUTS = {
    "old   (only job)": {"event": "shutdown", "job": "job-7"},
    "mixed (both, conflict)": {
        "event": "shutdown",
        "job": "job-7",
        "run_id": "run-9",
    },
    "new   (only run_id)": {"event": "shutdown", "run_id": "run-9"},
}


def show(mode: str) -> None:
    print(f"\n=== mode={mode!r} ===")
    migrator = FieldMigrator("job", "run_id", mode=mode)
    for label, event_dict in INPUTS.items():
        once = migrator(None, "info", dict(event_dict))
        twice = migrator(None, "info", dict(once))
        stable = "stable" if once == twice else "UNSTABLE"
        print(f"\n{label}:")
        print(f"  input : {json.dumps(event_dict, sort_keys=True)}")
        print(f"  pass 1: {json.dumps(once, sort_keys=True)}")
        print(f"  pass 2: {json.dumps(twice, sort_keys=True)}  [{stable}]")
        assert once == twice


def show_equivalence() -> None:
    print("\n=== structlog logger vs ProcessorFormatter ===")
    migrator = FieldMigrator("job", "run_id", mode="new-only")
    chain = [migrator, JSONRenderer()]

    cf = CapturingLoggerFactory()
    structlog.configure(processors=chain, logger_factory=cf)
    structlog.get_logger().info("shutdown", job="job-7")
    structlog_output = json.loads(cf.logger.calls[0].args[0])
    structlog.reset_defaults()

    formatter = ProcessorFormatter(
        foreign_pre_chain=[ExtraAdder(allow=["job"])],
        processors=[
            migrator,
            ProcessorFormatter.remove_processors_meta,
            JSONRenderer(),
        ],
    )
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    stdlib_logger = logging.getLogger("migration-demo")
    stdlib_logger.addHandler(handler)
    stdlib_logger.setLevel(logging.INFO)
    stdlib_logger.info("shutdown", extra={"job": "job-7"})
    stdlib_logger.removeHandler(handler)
    foreign_output = json.loads(stream.getvalue())

    print(f"  structlog: {json.dumps(structlog_output, sort_keys=True)}")
    print(f"  stdlib   : {json.dumps(foreign_output, sort_keys=True)}")
    assert structlog_output == foreign_output
    print("  -> identical")

    print("\n=== wrong position (after renderer) ===")
    rendered = JSONRenderer()(
        None, "info", {"event": "shutdown", "job": "job-7"}
    )
    try:
        migrator(None, "info", rendered)
    except TypeError as e:
        print(f"  TypeError: {e}")


if __name__ == "__main__":
    show("dual")
    show("new-only")
    show_equivalence()
    print("\nAll idempotency and equivalence checks passed.")
