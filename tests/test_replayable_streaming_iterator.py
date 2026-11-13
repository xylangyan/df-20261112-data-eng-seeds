# -*- coding: utf-8 -*-
import io

import pytest

from requests_toolbelt import (
    MultipartEncoder, ReplayableStreamingIterator, StreamingIterator,
    SourceNotReplayableError,
    )


class TrackedSource(io.BytesIO):
    """BytesIO that records whether it was explicitly closed."""

    def __init__(self, data, registry):
        super(TrackedSource, self).__init__(data)
        self.registry = registry
        self.was_closed = False
        registry.append(self)

    def close(self):
        self.was_closed = True
        super(TrackedSource, self).close()


@pytest.fixture
def payload():
    return b'0123456789abcdef' * 4  # 64 bytes


@pytest.fixture
def source_registry():
    return []


@pytest.fixture
def make_reopen(payload, source_registry):
    def reopen():
        return TrackedSource(payload, source_registry)
    return reopen


class TestReplayableStreamingIterator(object):
    def test_declared_size_is_kept_and_not_buffered(
            self, payload, make_reopen):
        streamer = ReplayableStreamingIterator(len(payload), make_reopen)
        assert streamer.size == len(payload)
        assert streamer.len == len(payload)
        # No source is opened until the first read, so nothing is buffered.
        assert streamer._file is None
        assert make_reopen  # callable stored untouched
        assert streamer.reopen is make_reopen

    def test_requires_a_callable(self, payload):
        with pytest.raises(TypeError):
            ReplayableStreamingIterator(len(payload), payload)

    def test_negative_size_is_rejected(self, make_reopen):
        with pytest.raises(ValueError):
            ReplayableStreamingIterator(-1, make_reopen)

    def test_source_without_read_is_rejected(self, payload):
        streamer = ReplayableStreamingIterator(len(payload), lambda: object())
        with pytest.raises(SourceNotReplayableError):
            streamer.read(8)

    def test_source_without_close_is_rejected(self, payload):
        class Readable(object):
            def read(self, size=-1):
                return b''

        streamer = ReplayableStreamingIterator(
            len(payload), lambda: Readable())
        with pytest.raises(SourceNotReplayableError):
            streamer.read(8)

    def test_reopen_failure_is_reported_with_reason(self, payload):
        def broken_reopen():
            raise RuntimeError('disk vanished')

        streamer = ReplayableStreamingIterator(
            len(payload), broken_reopen)
        with pytest.raises(SourceNotReplayableError) as exc:
            streamer.read(8)
        assert 'disk vanished' in str(exc.value)

    def test_wrong_declared_length_on_reopen_is_rejected(
            self, payload, source_registry):
        def reopen():
            return TrackedSource(payload + b'extra', source_registry)

        streamer = ReplayableStreamingIterator(len(payload), reopen)
        with pytest.raises(SourceNotReplayableError) as exc:
            streamer.read(8)
        assert 'advertises a length' in str(exc.value)

    def test_short_source_is_rejected_without_buffering(self):
        data = b'x' * 32

        class LengthlessSource(object):
            """Source with no discoverable length, like a socket stream."""

            def __init__(self):
                self._buffer = io.BytesIO(data)

            def read(self, size=-1):
                return self._buffer.read(size)

            def close(self):
                self._buffer.close()

        streamer = ReplayableStreamingIterator(
            64, lambda: LengthlessSource())
        chunks = []
        with pytest.raises(SourceNotReplayableError) as exc:
            while True:
                chunk = streamer.read(7)
                if not chunk:
                    break
                chunks.append(chunk)
        # The actual bytes were streamed, never accumulated up front.
        assert b''.join(chunks) == data
        message = str(exc.value)
        assert '32' in message and '64' in message

    def test_bounded_reads_never_exceed_requested_size(
            self, payload, make_reopen):
        streamer = ReplayableStreamingIterator(len(payload), make_reopen)
        total = 0
        while True:
            chunk = streamer.read(7)
            if not chunk:
                break
            assert len(chunk) <= 7
            total += len(chunk)
        assert total == len(payload)
        assert streamer.len == 0

    def test_reset_rewinds_to_first_byte_and_closes_old_source(
            self, payload, make_reopen, source_registry):
        streamer = ReplayableStreamingIterator(len(payload), make_reopen)

        # Round 1: a proxy that only reads the first 16 bytes then gives up.
        assert streamer.read(16) == payload[:16]
        assert len(source_registry) == 1
        assert source_registry[0].was_closed is False

        streamer.reset()

        assert len(source_registry) == 2
        assert source_registry[0].was_closed is True
        assert source_registry[1].was_closed is False
        assert streamer._bytes_read == 0
        assert streamer.size == len(payload)

        # Round 2: full upload, in bounded chunks.
        chunks = []
        while True:
            chunk = streamer.read(9)
            if not chunk:
                break
            chunks.append(chunk)
        assert b''.join(chunks) == payload
        assert len(b''.join(chunks)) == streamer.size

        # The second source is released explicitly when the body is done with.
        streamer.close()
        assert source_registry[1].was_closed is True
        assert all(source.was_closed for source in source_registry)

    def test_second_round_uses_a_fresh_source_after_clean_close(
            self, payload, make_reopen, source_registry):
        streamer = ReplayableStreamingIterator(len(payload), make_reopen)
        first = streamer.read(10)
        streamer.reset()
        second = streamer.read(10)
        assert first == second == payload[:10]
        assert source_registry[0].was_closed is True
        assert source_registry[1].was_closed is False

    def test_reading_past_the_end_does_not_reopen_a_source(
            self, payload, make_reopen, source_registry):
        streamer = ReplayableStreamingIterator(len(payload), make_reopen)
        while streamer.read(7):
            pass
        assert len(source_registry) == 1
        # Extra reads stay empty and must not silently open another source.
        assert streamer.read(7) == b''
        assert streamer.read() == b''
        assert len(source_registry) == 1
        assert source_registry[0].was_closed is True

    def test_source_producing_more_than_declared_is_rejected(self):
        class LengthlessSource(object):
            def __init__(self):
                self._buffer = io.BytesIO(b'x' * 96)

            def read(self, size=-1):
                return self._buffer.read(size)

            def close(self):
                self._buffer.close()

        streamer = ReplayableStreamingIterator(
            64, lambda: LengthlessSource())
        with pytest.raises(SourceNotReplayableError) as exc:
            while streamer.read(7):
                pass
        assert 'produced more than the declared 64 bytes' in str(exc.value)

    def test_a_third_round_starts_again_from_the_first_byte(
            self, payload, make_reopen, source_registry):
        streamer = ReplayableStreamingIterator(len(payload), make_reopen)
        for _ in range(3):
            streamer.read(12)
            streamer.reset()
        # One initial open plus one fresh source per reset.
        assert len(source_registry) == 4
        assert all(source.was_closed for source in source_registry[:3])
        assert streamer.read(8) == payload[:8]


class TestReplayableMultipartPart(object):
    def _encoder(self, payload, make_reopen):
        streamer = ReplayableStreamingIterator(len(payload), make_reopen)
        return MultipartEncoder(
            [('file', ('collection.bin', streamer,
                       'application/octet-stream'))],
            boundary='replay-boundary',
            )

    def test_part_contract_replays_the_body(
            self, payload, make_reopen, source_registry):
        encoder = self._encoder(payload, make_reopen)
        declared_length = encoder.len

        # Round 1: only part of the body is read before resubmission.
        partial = encoder.read(declared_length - 10)
        assert len(partial) == declared_length - 10
        assert len(source_registry) == 1
        assert source_registry[0].was_closed is False

        encoder.reset()

        assert encoder.len == declared_length
        assert source_registry[0].was_closed is True
        assert source_registry[1].was_closed is False

        # Round 2: complete upload, bounded reads, from the first byte.
        chunks = []
        while True:
            chunk = encoder.read(8)
            if not chunk:
                break
            assert len(chunk) <= 8
            chunks.append(chunk)
        body = b''.join(chunks)
        assert len(body) == declared_length
        assert body.startswith(b'--replay-boundary\r\n')
        assert payload in body

        encoder.close()
        assert all(source.was_closed for source in source_registry)
        assert len(source_registry) == 2

    def test_one_pass_part_cannot_be_replayed(self):
        streamer = StreamingIterator(3, iter([b'abc']))
        encoder = MultipartEncoder(
            [('file', ('collection.bin', streamer,
                       'application/octet-stream'))],
            )
        encoder.read(8)
        with pytest.raises(SourceNotReplayableError) as exc:
            encoder.reset()
        assert 'one-pass source' in str(exc.value)

    def test_seekable_part_can_be_replayed(self, payload):
        encoder = MultipartEncoder(
            [('file', ('collection.bin', io.BytesIO(payload),
                       'application/octet-stream'))],
            boundary='replay-boundary',
            )
        declared_length = encoder.len
        first = encoder.read(20)
        encoder.reset()
        assert encoder.len == declared_length
        second = encoder.read()
        assert second.startswith(b'--replay-boundary\r\n')
        assert second.startswith(first[:10])
        assert len(second) == declared_length
