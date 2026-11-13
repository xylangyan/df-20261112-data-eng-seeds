# SPDX-License-Identifier: MIT OR Apache-2.0
# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the MIT License.  See the LICENSE file in the root of this
# repository for complete details.

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import pickle
import sys
import threading

from io import StringIO

import pytest

import structlog

from structlog import BoundLogger
from structlog._utils import get_processname
from structlog.processors import (
    CallsiteParameter,
    CallsiteParameterAdder,
    EventRenamer,
    ExceptionPrettyPrinter,
    FieldMigrator,
    JSONRenderer,
    StackInfoRenderer,
    UnicodeDecoder,
    UnicodeEncoder,
    _figure_out_exc_info,
    format_exc_info,
)
from structlog.stdlib import ProcessorFormatter
from structlog.testing import CapturingLoggerFactory
from structlog.typing import EventDict, ExcInfo

from ..additional_frame import additional_frame


try:
    import simplejson
except ImportError:
    simplejson = None


class TestUnicodeEncoder:
    def test_encodes(self):
        """
        Unicode strings get encoded (as UTF-8 by default).
        """
        e = UnicodeEncoder()

        assert {"foo": b"b\xc3\xa4r"} == e(None, None, {"foo": "b\xe4r"})

    def test_passes_arguments(self):
        """
        Encoding options are passed into the encoding call.
        """
        e = UnicodeEncoder("latin1", "xmlcharrefreplace")

        assert {"foo": b"&#8211;"} == e(None, None, {"foo": "\u2013"})

    def test_bytes_nop(self):
        """
        If the string is already bytes, don't do anything.
        """
        e = UnicodeEncoder()

        assert {"foo": b"b\xc3\xa4r"} == e(None, None, {"foo": b"b\xc3\xa4r"})


class TestUnicodeDecoder:
    def test_decodes(self):
        """
        Byte strings get decoded (as UTF-8 by default).
        """
        ud = UnicodeDecoder()

        assert {"foo": "b\xe4r"} == ud(None, None, {"foo": b"b\xc3\xa4r"})

    def test_passes_arguments(self):
        """
        Encoding options are passed into the encoding call.
        """
        ud = UnicodeDecoder("utf-8", "ignore")

        assert {"foo": ""} == ud(None, None, {"foo": b"\xa1\xa4"})

    def test_bytes_nop(self):
        """
        If the value is already unicode, don't do anything.
        """
        ud = UnicodeDecoder()

        assert {"foo": "b\u2013r"} == ud(None, None, {"foo": "b\u2013r"})


class TestExceptionPrettyPrinter:
    def test_stdout_by_default(self):
        """
        If no file is supplied, use stdout.
        """
        epp = ExceptionPrettyPrinter()

        assert sys.stdout is epp._file

    def test_prints_exception(self, sio):
        """
        If there's an `exception` key in the event_dict, just print it out.
        This happens if `format_exc_info` was run before us in the chain.
        """
        epp = ExceptionPrettyPrinter(file=sio)
        try:
            raise ValueError
        except ValueError:
            ed = format_exc_info(None, None, {"exc_info": True})
        epp(None, None, ed)

        out = sio.getvalue()

        assert "test_prints_exception" in out
        assert "raise ValueError" in out

    def test_uses_exception_formatter(self, sio):
        """
        If an `exception_formatter` is passed, use that to render the
        exception rather than the default.
        """

        def formatter(exc_info: ExcInfo) -> str:
            return f"error: {exc_info}"

        epp = ExceptionPrettyPrinter(file=sio, exception_formatter=formatter)
        try:
            raise ValueError
        except ValueError as e:
            epp(None, None, {"exc_info": True})
            formatted = formatter(e)

        out = sio.getvalue()

        assert formatted in out

    def test_removes_exception_after_printing(self, sio):
        """
        After pretty printing `exception` is removed from the event_dict.
        """
        epp = ExceptionPrettyPrinter(sio)
        try:
            raise ValueError
        except ValueError:
            ed = format_exc_info(None, None, {"exc_info": True})

        assert "exception" in ed

        new_ed = epp(None, None, ed)

        assert "exception" not in new_ed

    def test_handles_exc_info(self, sio):
        """
        If `exc_info` is passed in, it behaves like `format_exc_info`.
        """
        epp = ExceptionPrettyPrinter(sio)
        try:
            raise ValueError
        except ValueError:
            epp(None, None, {"exc_info": True})

        out = sio.getvalue()

        assert "test_handles_exc_info" in out
        assert "raise ValueError" in out

    def test_removes_exc_info_after_printing(self, sio):
        """
        After pretty printing `exception` is removed from the event_dict.
        """
        epp = ExceptionPrettyPrinter(sio)
        try:
            raise ValueError
        except ValueError:
            ed = epp(None, None, {"exc_info": True})

        assert "exc_info" not in ed

    def test_nop_if_no_exception(self, sio):
        """
        If there is no exception, don't print anything.
        """
        epp = ExceptionPrettyPrinter(sio)
        epp(None, None, {})

        assert "" == sio.getvalue()

    def test_own_exc_info(self, sio):
        """
        If exc_info is a tuple, use it.
        """
        epp = ExceptionPrettyPrinter(sio)
        try:
            raise ValueError("XXX")
        except ValueError:
            ei = sys.exc_info()

        epp(None, None, {"exc_info": ei})

        assert "XXX" in sio.getvalue()

    def test_exception_on_py3(self, sio):
        """
        On Python 3, it's also legal to pass an Exception.
        """
        epp = ExceptionPrettyPrinter(sio)
        try:
            raise ValueError("XXX")
        except ValueError as e:
            epp(None, None, {"exc_info": e})

        assert "XXX" in sio.getvalue()


@pytest.fixture
def sir():
    return StackInfoRenderer()


class TestStackInfoRenderer:
    def test_removes_stack_info(self, sir):
        """
        The `stack_info` key is removed from `event_dict`.
        """
        ed = sir(None, None, {"stack_info": True})

        assert "stack_info" not in ed

    def test_adds_stack_if_asked(self, sir):
        """
        If `stack_info` is true, `stack` is added.
        """
        ed = sir(None, None, {"stack_info": True})

        assert "stack" in ed

    def test_renders_correct_stack(self, sir):
        """
        The rendered stack is correct.
        """
        ed = sir(None, None, {"stack_info": True})

        assert 'ed = sir(None, None, {"stack_info": True})' in ed["stack"]

    def test_additional_ignores(self):
        """
        Filtering of names works.
        """
        sir = StackInfoRenderer(["tests.additional_frame"])

        ed = additional_frame(
            functools.partial(sir, None, None, {"stack_info": True})
        )

        assert "additional_frame.py" not in ed["stack"]


class TestFigureOutExcInfo:
    @pytest.mark.parametrize("true_value", [True, 1, 1.1])
    def test_obtains_exc_info_on_True(self, true_value):
        """
        If the passed argument evaluates to True obtain exc_info ourselves.
        """
        try:
            0 / 0
        except Exception:
            assert sys.exc_info() == _figure_out_exc_info(true_value)
        else:
            pytest.fail("Exception not raised.")

    def test_py3_exception_no_traceback(self):
        """
        Exceptions without tracebacks are simply returned with None for
        traceback.
        """
        e = ValueError()

        assert (e.__class__, e, None) == _figure_out_exc_info(e)


class TestCallsiteParameterAdder:
    parameter_strings = {
        "pathname",
        "filename",
        "module",
        "func_name",
        "lineno",
        "thread",
        "thread_name",
        "process",
        "process_name",
    }

    # Exclude QUAL_NAME and QUAL_MODULE from the general set to keep parity with
    # stdlib LogRecord-derived parameters. QUAL_NAME and QUAL_MODULE are tested
    # separately.
    _all_parameters = {
        p
        for p in set(CallsiteParameter)
        if p
        not in (CallsiteParameter.QUAL_NAME, CallsiteParameter.QUAL_MODULE)
    }

    def test_all_parameters(self) -> None:
        """
        All callsite parameters are included in ``self.parameter_strings`` and
        the dictionary returned by ``self.get_callsite_parameters`` contains
        keys for all callsite parameters.
        """

        assert self.parameter_strings == {
            member.value for member in self._all_parameters
        }
        assert self.parameter_strings == self.get_callsite_parameters().keys()

    @pytest.mark.skipif(
        sys.version_info < (3, 11), reason="QUAL_NAME requires Python 3.11+"
    )
    def test_qual_name_structlog(self) -> None:
        """
        QUAL_NAME is added for structlog-originated events on Python 3.11+.
        """
        processor = CallsiteParameterAdder(
            parameters={CallsiteParameter.QUAL_NAME}
        )
        event_dict: EventDict = {"event": "msg"}
        actual = processor(None, None, event_dict)

        assert actual["qual_name"].endswith(
            f"{self.__class__.__name__}.test_qual_name_structlog"
        )

    def test_qual_module_structlog(self) -> None:
        """
        QUAL_MODULE is added for structlog-originated events.
        """
        processor = CallsiteParameterAdder(
            parameters={CallsiteParameter.QUAL_MODULE}
        )
        event_dict: EventDict = {"event": "msg"}
        actual = processor(None, None, event_dict)

        assert "tests.processors.test_processors" == actual["qual_module"]

    def test_qual_name_logging_origin_absent(self) -> None:
        """
        QUAL_NAME is not sourced from stdlib LogRecord and remains absent
        (because it doesn't exist).
        """
        processor = CallsiteParameterAdder(
            parameters={CallsiteParameter.QUAL_NAME}
        )
        record = logging.LogRecord(
            "name",
            logging.INFO,
            __file__,
            0,
            "message",
            None,
            None,
            "func",
        )
        event_dict: EventDict = {
            "event": "message",
            "_record": record,
            "_from_structlog": False,
        }
        actual = processor(None, None, event_dict)

        assert "qual_name" not in actual

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("wrapper_class", "method_name"),
        [
            (structlog.stdlib.BoundLogger, "ainfo"),
            (structlog.stdlib.AsyncBoundLogger, "info"),
        ],
    )
    async def test_async(self, wrapper_class, method_name) -> None:
        """
        Callsite information for async invocations are correct.
        Thread information is now correctly captured before async bridge.
        """
        string_io = StringIO()

        class StringIOLogger(structlog.PrintLogger):
            def __init__(self):
                super().__init__(file=string_io)

        processor = self.make_processor(None, ["concurrent", "threading"])
        structlog.configure(
            processors=[processor, JSONRenderer()],
            logger_factory=StringIOLogger,
            wrapper_class=wrapper_class,
            cache_logger_on_first_use=True,
        )

        logger = structlog.stdlib.get_logger()

        # Capture thread info before async call
        expected_thread = threading.get_ident()
        expected_thread_name = threading.current_thread().name

        callsite_params = self.get_callsite_parameters()
        await getattr(logger, method_name)("baz")
        logger_params = json.loads(string_io.getvalue())

        assert expected_thread == logger_params["thread"]
        assert expected_thread_name == logger_params["thread_name"]

        # Remove thread info from comparison for remaining params
        for key in ["thread", "thread_name"]:
            callsite_params.pop(key)
            logger_params.pop(key)

        assert {"event": "baz", **callsite_params} == logger_params

    @pytest.mark.asyncio
    async def test_async_native_logger(self) -> None:
        """
        Callsite thread information for native async invocations is correct.
        """
        cf = CapturingLoggerFactory()
        structlog.configure(
            processors=[
                CallsiteParameterAdder(
                    parameters=[
                        CallsiteParameter.THREAD,
                        CallsiteParameter.THREAD_NAME,
                    ]
                ),
            ],
            logger_factory=cf,
            wrapper_class=structlog._native.BoundLoggerFilteringAtInfo,
            cache_logger_on_first_use=True,
        )

        logger = structlog.get_logger()

        expected_thread = threading.get_ident()
        expected_thread_name = threading.current_thread().name

        await logger.ainfo("test native async")

        captured = cf.logger.calls[0].kwargs

        assert expected_thread == captured["thread"]
        assert expected_thread_name == captured["thread_name"]

    def test_additional_ignores(self) -> None:
        """
        Stack frames from modules with names that start with values in
        `additional_ignores` are ignored when determining the callsite.
        """
        test_message = "test message"
        additional_ignores = ["tests.additional_frame"]
        processor = self.make_processor(None, additional_ignores)
        event_dict: EventDict = {"event": test_message}

        # Warning: the next two lines must appear exactly like this to make
        # line numbers match.
        callsite_params = self.get_callsite_parameters(1)
        actual = processor(None, None, event_dict)

        expected = {"event": test_message, **callsite_params}

        assert expected == actual

    @pytest.mark.parametrize("origin", ["logging", "structlog"])
    @pytest.mark.parametrize(
        "parameter_strings",
        [
            None,
            *[{parameter} for parameter in parameter_strings],
            set(),
            parameter_strings,
            {"pathname", "filename"},
            {"module", "func_name"},
        ],
    )
    def test_processor(
        self,
        origin: str,
        parameter_strings: set[str] | None,
    ):
        """
        The correct callsite parameters are added to event dictionaries.
        """
        test_message = "test message"
        processor = self.make_processor(parameter_strings)
        if origin == "structlog":
            event_dict: EventDict = {"event": test_message}
            callsite_params = self.get_callsite_parameters()
            actual = processor(None, None, event_dict)
        elif origin == "logging":
            callsite_params = self.get_callsite_parameters()
            record = logging.LogRecord(
                "name",
                logging.INFO,
                callsite_params["pathname"],
                callsite_params["lineno"],
                test_message,
                None,
                None,
                callsite_params["func_name"],
            )
            event_dict: EventDict = {
                "event": test_message,
                "_record": record,
                "_from_structlog": False,
            }
            actual = processor(None, None, event_dict)
        else:
            pytest.fail(f"invalid origin {origin}")
        actual = {
            key: value
            for key, value in actual.items()
            if not key.startswith("_")
        }
        callsite_params = self.filter_parameter_dict(
            callsite_params, parameter_strings
        )
        expected = {"event": test_message, **callsite_params}

        assert expected == actual

    @pytest.mark.parametrize(
        "setup",
        ["common-without-pre", "common-with-pre", "shared", "everywhere"],
    )
    @pytest.mark.parametrize("origin", ["logging", "structlog"])
    @pytest.mark.parametrize(
        "parameter_strings",
        [
            None,
            *[{parameter} for parameter in parameter_strings],
            set(),
            parameter_strings,
            {"pathname", "filename"},
            {"module", "func_name"},
        ],
    )
    def test_e2e(
        self,
        setup: str,
        origin: str,
        parameter_strings: set[str] | None,
    ) -> None:
        """
        Logging output contains the correct callsite parameters.
        """
        logger = logging.Logger(sys._getframe().f_code.co_name)
        string_io = StringIO()
        handler = logging.StreamHandler(string_io)
        processors = [self.make_processor(parameter_strings)]
        if setup == "common-without-pre":
            common_processors = processors
            formatter = ProcessorFormatter(
                processors=[*processors, JSONRenderer()]
            )
        elif setup == "common-with-pre":
            common_processors = processors
            formatter = ProcessorFormatter(
                foreign_pre_chain=processors,
                processors=[JSONRenderer()],
            )
        elif setup == "shared":
            common_processors = []
            formatter = ProcessorFormatter(
                processors=[*processors, JSONRenderer()],
            )
        elif setup == "everywhere":
            common_processors = processors
            formatter = ProcessorFormatter(
                foreign_pre_chain=processors,
                processors=[*processors, JSONRenderer()],
            )
        else:
            pytest.fail(f"invalid setup {setup}")
        handler.setFormatter(formatter)
        handler.setLevel(0)
        logger.addHandler(handler)
        logger.setLevel(0)

        test_message = "test message"
        if origin == "logging":
            callsite_params = self.get_callsite_parameters()
            logger.info(test_message)
        elif origin == "structlog":
            ctx = {}
            bound_logger = BoundLogger(
                logger,
                [*common_processors, ProcessorFormatter.wrap_for_formatter],
                ctx,
            )
            callsite_params = self.get_callsite_parameters()
            bound_logger.info(test_message)
        else:
            pytest.fail(f"invalid origin {origin}")

        callsite_params = self.filter_parameter_dict(
            callsite_params, parameter_strings
        )
        actual = {
            key: value
            for key, value in json.loads(string_io.getvalue()).items()
            if not key.startswith("_")
        }
        expected = {"event": test_message, **callsite_params}

        assert expected == actual

    def test_pickeable_callsite_parameter_adder(self) -> None:
        """
        An instance of ``CallsiteParameterAdder`` can be pickled.  This
        functionality may be used to propagate structlog configurations to
        subprocesses.
        """
        pickle.dumps(CallsiteParameterAdder())

    @classmethod
    def make_processor(
        cls,
        parameter_strings: set[str] | None,
        additional_ignores: list[str] | None = None,
    ) -> CallsiteParameterAdder:
        """
        Creates a ``CallsiteParameterAdder`` with parameters matching the
        supplied *parameter_strings* values and with the supplied
        *additional_ignores* values.

        Args:
            parameter_strings:
                Strings for which corresponding ``CallsiteParameters`` should
                be included in the resulting ``CallsiteParameterAdded``.

            additional_ignores:
                Used as *additional_ignores* for the resulting
                ``CallsiteParameterAdded``.
        """
        if parameter_strings is None:
            return CallsiteParameterAdder(
                parameters=cls._all_parameters,
                additional_ignores=additional_ignores,
            )

        parameters = cls.filter_parameters(parameter_strings)
        return CallsiteParameterAdder(
            parameters=parameters,
            additional_ignores=additional_ignores,
        )

    @classmethod
    def filter_parameters(
        cls, parameter_strings: set[str] | None
    ) -> set[CallsiteParameter]:
        """
        Returns a set containing all ``CallsiteParameter`` members with values
        that are in ``parameter_strings``.

        Args:
            parameter_strings:
                The parameters strings for which corresponding
                ``CallsiteParameter`` members should be returned. If this value
                is `None` then all ``CallsiteParameter`` will be returned.
        """
        if parameter_strings is None:
            return cls._all_parameters
        return {
            parameter
            for parameter in cls._all_parameters
            if parameter.value in parameter_strings
        }

    @classmethod
    def filter_parameter_dict(
        cls, input: dict[str, object], parameter_strings: set[str] | None
    ) -> dict[str, object]:
        """
        Returns a dictionary that is equivalent to *input* but with all keys
        not in *parameter_strings* removed.

        Args:
            parameter_strings:
                The keys to keep in the dictionary, if this value is ``None``
                then all keys matching ``cls.parameter_strings`` are kept.
        """
        if parameter_strings is None:
            parameter_strings = cls.parameter_strings
        return {
            key: value
            for key, value in input.items()
            if key in parameter_strings
        }

    @classmethod
    def get_callsite_parameters(cls, offset: int = 1) -> dict[str, object]:
        """
        This function creates dictionary of callsite parameters for the line
        that is ``offset`` lines after the invocation of this function.

        Args:
            offset:
                The amount of lines after the invocation of this function that
                callsite parameters should be generated for.
        """
        frame_info = inspect.stack()[1]
        frame_traceback = inspect.getframeinfo(frame_info[0])
        return {
            "pathname": frame_traceback.filename,
            "filename": os.path.basename(frame_traceback.filename),
            "module": os.path.splitext(
                os.path.basename(frame_traceback.filename)
            )[0],
            "func_name": frame_info.function,
            "lineno": frame_info.lineno + offset,
            "thread": threading.get_ident(),
            "thread_name": threading.current_thread().name,
            "process": os.getpid(),
            "process_name": get_processname(),
        }


class TestRenameKey:
    def test_rename_once(self):
        """
        Renaming event to something else works.
        """
        assert {"msg": "hi", "foo": "bar"} == EventRenamer("msg")(
            None, None, {"event": "hi", "foo": "bar"}
        )

    def test_rename_twice(self):
        """
        Renaming both from and to `event` works.
        """
        assert {
            "msg": "hi",
            "event": "fabulous",
            "foo": "bar",
        } == EventRenamer("msg", "_event")(
            None, None, {"event": "hi", "foo": "bar", "_event": "fabulous"}
        )

    def test_replace_by_key_is_optional(self):
        """
        The key that is renamed to `event` doesn't have to exist.
        """
        assert {"msg": "hi", "foo": "bar"} == EventRenamer("msg", "missing")(
            None, None, {"event": "hi", "foo": "bar"}
        )


def _migrate(event_dict, **kwargs):
    defaults = dict(old_key="job", new_key="run_id")
    defaults.update(kwargs)
    return FieldMigrator(**defaults)(None, "info", dict(event_dict))


def _run_twice(event_dict, **kwargs):
    once = _migrate(event_dict, **kwargs)
    twice = _migrate(once, **kwargs)
    return once, twice


class TestFieldMigrator:
    def test_missing_field_is_left_alone(self):
        """
        Events without either key are not touched and get no marker.
        """
        event_dict = {"event": "hi"}

        assert {"event": "hi"} == _migrate(event_dict)

    @pytest.mark.parametrize("mode", ["dual", "new-only"])
    def test_explicit_null_is_a_real_value(self, mode):
        """
        An explicit None is migrated and never conflated with missing.
        """
        once, twice = _run_twice(
            {"event": "hi", "job": None}, mode=mode
        )

        assert once["run_id"] is None
        assert once["_field_migration"]["rule"] == "old_only"
        assert twice == once

    def test_old_only_dual_writes_both_names(self):
        """
        In dual mode the value is written under both names.
        """
        once, twice = _run_twice({"event": "hi", "job": "job-1"})

        assert once == {
            "event": "hi",
            "job": "job-1",
            "run_id": "job-1",
            "_field_migration": {
                "old_key": "job",
                "new_key": "run_id",
                "rule": "old_only",
            },
        }
        assert twice == once

    def test_old_only_new_only_drops_old_name(self):
        """
        In new-only mode the old name is removed.
        """
        once, twice = _run_twice(
            {"event": "hi", "job": "job-1"}, mode="new-only"
        )

        assert once == {
            "event": "hi",
            "run_id": "job-1",
            "_field_migration": {
                "old_key": "job",
                "new_key": "run_id",
                "rule": "old_only",
            },
        }
        assert twice == once

    def test_new_only_input_passes_through_unchanged(self):
        """
        Logs already in the new format don't change, no marker added.
        """
        event_dict = {"event": "hi", "run_id": "run-1"}

        once, twice = _run_twice(event_dict)

        assert once == event_dict
        assert twice == event_dict

    def test_mixed_equal_values_pass_through_unchanged(self):
        """
        Both names with the same value need no normalization.
        """
        event_dict = {"event": "hi", "job": "x", "run_id": "x"}

        assert _migrate(event_dict) == event_dict

    @pytest.mark.parametrize("mode", ["dual", "new-only"])
    def test_conflict_new_wins_and_marks_rule(self, mode):
        """
        Conflicts are resolved deterministically and the rule recorded.
        """
        once, twice = _run_twice(
            {"event": "hi", "job": "old-1", "run_id": "new-1"},
            mode=mode,
        )

        assert once["run_id"] == "new-1"
        assert once["_field_migration"]["rule"] == "conflict_new_wins"
        if mode == "dual":
            assert once["job"] == "new-1"
        else:
            assert "job" not in once
        assert twice == once

    def test_conflict_old_wins(self):
        """
        on_conflict='old' keeps the old value and marks the rule.
        """
        once, twice = _run_twice(
            {"job": "old-1", "run_id": "new-1"}, on_conflict="old"
        )

        assert once["run_id"] == "old-1"
        assert once["job"] == "old-1"
        assert once["_field_migration"]["rule"] == "conflict_old_wins"
        assert twice == once

    def test_conflict_error_raises(self):
        """
        on_conflict='error' raises instead of picking a side.
        """
        with pytest.raises(ValueError, match="Conflicting values"):
            _migrate({"job": "old-1", "run_id": "new-1"}, on_conflict="error")

    def test_conflict_between_null_and_value_is_still_conflict(self):
        """
        An explicit None next to a real value is a conflict, not missing.
        """
        once = _migrate({"job": None, "run_id": "new-1"})

        assert once["run_id"] == "new-1"
        assert once["_field_migration"]["rule"] == "conflict_new_wins"

    def test_marker_can_be_disabled(self):
        """
        marker_key=None disables recording without changing migration.
        """
        once = _migrate({"job": "job-1"}, marker_key=None)

        assert once == {"job": "job-1", "run_id": "job-1"}

    def test_invalid_constructor_args(self):
        with pytest.raises(ValueError, match="mode"):
            FieldMigrator("job", "run_id", mode="sideways")
        with pytest.raises(ValueError, match="on_conflict"):
            FieldMigrator("job", "run_id", on_conflict="coin-flip")

    def test_rendered_event_raises_helpful_type_error(self):
        """
        Placing the processor after a renderer gives a clear hint.
        """
        chain = [FieldMigrator("job", "run_id"), JSONRenderer()]
        rendered = chain[1](None, "info", {"event": "hi", "job": "j"})

        with pytest.raises(TypeError, match="before the renderer"):
            chain[0](None, "info", rendered)

    def test_structlog_logger_chain(self):
        """
        Works end to end through a configured structlog logger.
        """
        cf = CapturingLoggerFactory()
        structlog.configure(
            processors=[
                FieldMigrator("job", "run_id", mode="new-only"),
                JSONRenderer(),
            ],
            logger_factory=cf,
        )
        try:
            structlog.get_logger().info("hi", job="job-1")
        finally:
            structlog.reset_defaults()

        payload = json.loads(cf.logger.calls[0].args[0])
        assert payload["run_id"] == "job-1"
        assert "job" not in payload
        assert payload["_field_migration"]["rule"] == "old_only"

    def test_structlog_and_processor_formatter_agree(self):
        """
        structlog and stdlib records get identical processed output.
        """
        migrator = FieldMigrator("job", "run_id", mode="new-only")
        formatter = ProcessorFormatter(
            foreign_pre_chain=[structlog.stdlib.ExtraAdder(allow=["job"])],
            processors=[
                migrator,
                ProcessorFormatter.remove_processors_meta,
                JSONRenderer(),
            ],
        )
        structlog.configure(
            processors=[
                migrator,
                ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
        )
        stdlib_logger = logging.getLogger("field-migration-test")
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        stdlib_logger.addHandler(handler)
        stdlib_logger.setLevel(logging.INFO)

        try:
            structlog.get_logger("field-migration-test").info(
                "hi", job="job-1"
            )
            structlog_payload = json.loads(stream.getvalue())
            stream.seek(0)
            stream.truncate()
            stdlib_logger.info("hi", extra={"job": "job-1"})
            foreign_payload = json.loads(stream.getvalue())
        finally:
            stdlib_logger.removeHandler(handler)
            structlog.reset_defaults()

        assert structlog_payload == foreign_payload
