# -*- coding: utf-8 -*-
import math
import unittest
from requests_toolbelt.multipart.encoder import (
    IDENTITY, MonitorReadState, MultipartEncoder,
    MultipartEncoderMonitor,
    )


class TestMultipartEncoderMonitor(unittest.TestCase):
    def setUp(self):
        self.fields = {'a': 'b'}
        self.boundary = 'thisisaboundary'
        self.encoder = MultipartEncoder(self.fields, self.boundary)
        self.monitor = MultipartEncoderMonitor(self.encoder)

    def test_content_type(self):
        assert self.monitor.content_type == self.encoder.content_type

    def test_length(self):
        assert self.encoder.len == self.monitor.len

    def test_read(self):
        new_encoder = MultipartEncoder(self.fields, self.boundary)
        assert new_encoder.read() == self.monitor.read()

    def test_callback_called_when_reading_everything(self):
        callback = Callback(self.monitor)
        self.monitor.callback = callback
        self.monitor.read()
        assert callback.called == 1

    def test_callback(self):
        callback = Callback(self.monitor)
        self.monitor.callback = callback
        chunk_size = int(math.ceil(self.encoder.len / 4.0))
        while self.monitor.read(chunk_size):
            pass
        # One callback per non-empty read; the final read completes the body
        # and the trailing empty EOF read no longer fires the callback.
        assert callback.called == 4

    def test_bytes_read(self):
        bytes_to_read = self.encoder.len
        self.monitor.read()
        assert self.monitor.bytes_read == bytes_to_read

    def test_default_callable_is_the_identity(self):
        assert self.monitor.callback == IDENTITY
        assert IDENTITY(1) == 1

    def test_from_fields(self):
        monitor = MultipartEncoderMonitor.from_fields(
            self.fields, self.boundary
            )
        assert isinstance(monitor, MultipartEncoderMonitor)
        assert isinstance(monitor.encoder, MultipartEncoder)
        assert monitor.encoder.boundary_value == self.boundary


class SegmentPart(object):
    """Small in-memory part that records every ``read`` call it serves."""

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.read_calls = []

    def __len__(self):
        return len(self.data) - self.pos

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.data) - self.pos
        size = min(size, len(self.data) - self.pos)
        self.read_calls.append(size)
        chunk = self.data[self.pos:self.pos + size]
        self.pos += len(chunk)
        return chunk


class FailingPart(object):
    """Part that raises after ``fail_after`` bytes have been served."""

    def __init__(self, data, fail_after):
        self.data = data
        self.pos = 0
        self.fail_after = fail_after

    def __len__(self):
        return len(self.data) - self.pos

    def read(self, size=-1):
        if self.pos >= self.fail_after:
            raise IOError('boom after %d bytes' % self.pos)
        if size is None or size < 0:
            size = len(self.data) - self.pos
        size = min(size, self.fail_after - self.pos)
        chunk = self.data[self.pos:self.pos + size]
        self.pos += len(chunk)
        return chunk


class RecordingCallback(object):
    """Captures a monitor snapshot on every callback invocation."""

    def __init__(self):
        self.snapshots = []

    def __call__(self, monitor):
        self.snapshots.append(
            (monitor.state, monitor.bytes_read, monitor.len,
             monitor.finished, monitor.error)
            )


class TestMonitorReadState(unittest.TestCase):
    def setUp(self):
        self.fields = {'a': 'b'}
        self.boundary = 'thisisaboundary'

    def _monitor(self, fields=None):
        encoder = MultipartEncoder(
            fields or self.fields, boundary=self.boundary
            )
        monitor = MultipartEncoderMonitor(encoder)
        callback = RecordingCallback()
        monitor.callback = callback
        return monitor, callback

    def test_read_zero_probe_does_not_count_or_callback(self):
        monitor, callback = self._monitor()
        assert monitor.read(0) == b''
        assert callback.snapshots == []
        assert monitor.bytes_read == 0
        assert monitor.state == MonitorReadState.READING
        assert monitor.finished is False

    def test_eof_terminal_state_announced_once(self):
        monitor, callback = self._monitor()
        chunk_size = int(math.ceil(monitor.len / 4.0))
        read_log = []
        while True:
            requested = chunk_size
            returned = monitor.read(requested)
            read_log.append((requested, len(returned)))
            if not returned:
                break

        assert read_log[0][0] == chunk_size
        assert all(returned >= 0 for _, returned in read_log)
        assert monitor.bytes_read == monitor.len
        assert monitor.state == MonitorReadState.FINISHED
        assert monitor.finished is True
        assert monitor.error is None

        terminal = [s for s in callback.snapshots
                    if s[0] == MonitorReadState.FINISHED]
        assert len(terminal) == 1
        assert terminal[0][1] == monitor.len

        announced = len(callback.snapshots)
        assert monitor.read(chunk_size) == b''
        assert monitor.read(0) == b''
        assert monitor.read() == b''
        assert len(callback.snapshots) == announced

    def test_last_nonempty_chunk_precedes_terminal_callback(self):
        monitor, callback = self._monitor()
        last_chunk = None
        while True:
            chunk = monitor.read(7)
            if not chunk:
                break
            last_chunk = chunk

        # The read that completes the body (here the final non-empty chunk)
        # transitions to the terminal state exactly once; earlier reads stay
        # in the reading state.
        assert last_chunk is not None
        assert len(last_chunk) <= 7
        assert monitor.bytes_read == monitor.len
        assert monitor.state == MonitorReadState.FINISHED
        assert callback.snapshots[-1][0] == MonitorReadState.FINISHED
        assert callback.snapshots[-1][1] == monitor.len
        assert all(s[0] == MonitorReadState.READING
                   for s in callback.snapshots[:-1])
        terminal = [s for s in callback.snapshots
                    if s[0] == MonitorReadState.FINISHED]
        assert len(terminal) == 1

    def test_bytes_read_reflects_actual_returned_length(self):
        monitor, callback = self._monitor()
        total = 0
        while True:
            returned = monitor.read(5)
            total += len(returned)
            if not returned:
                break
            assert monitor.bytes_read == total
        assert total == monitor.len

    def test_read_error_enters_failed_terminal_state_once(self):
        body = FailingPart(b'0123456789' * 8, fail_after=25)
        monitor, callback = self._monitor({'f': body})
        assert monitor.state == MonitorReadState.READING

        with self.assertRaises(IOError):
            while True:
                monitor.read(16)

        assert monitor.state == MonitorReadState.FAILED
        assert monitor.finished is True
        assert isinstance(monitor.error, IOError)
        assert monitor.bytes_read < monitor.len

        failed = [s for s in callback.snapshots
                  if s[0] == MonitorReadState.FAILED]
        assert len(failed) == 1
        assert failed[0][4] is monitor.error

        announced = len(callback.snapshots)
        with self.assertRaises(IOError):
            monitor.read(16)
        assert len(callback.snapshots) == announced
        assert monitor.state == MonitorReadState.FAILED

    def test_part_read_calls_record_every_segment(self):
        part = SegmentPart(b'x' * 30)
        monitor, callback = self._monitor({'f': part})
        read_log = []
        while True:
            requested = 10
            returned = monitor.read(requested)
            read_log.append((requested, len(returned)))
            if not returned:
                break

        assert all(size > 0 for size in part.read_calls)
        assert sum(part.read_calls) == len(part.data)
        assert read_log[-1] == (10, 0)
        assert monitor.bytes_read == monitor.len
        assert monitor.state == MonitorReadState.FINISHED
        assert all(s[1] <= monitor.len for s in callback.snapshots)

    def test_normal_read_to_completion_snapshots(self):
        monitor, callback = self._monitor()
        while True:
            chunk = monitor.read(8)
            if not chunk:
                break
        states = [s[0] for s in callback.snapshots]
        assert states[0] == MonitorReadState.READING
        assert states[-1] == MonitorReadState.FINISHED
        assert states.count(MonitorReadState.FINISHED) == 1
        assert callback.snapshots[-1][1] == monitor.len


class Callback(object):
    def __init__(self, monitor):
        self.called = 0
        self.monitor = monitor

    def __call__(self, monitor):
        self.called += 1
        assert monitor == self.monitor
