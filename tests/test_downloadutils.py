"""Tests for the utils module."""
import io
import os
import os.path
import shutil
import tempfile

import requests
from requests_toolbelt.downloadutils import stream
from requests_toolbelt.downloadutils import tee
try:
    from unittest import mock
except ImportError:
    import mock
import pytest

from . import get_betamax


preserve_bytes = {'preserve_exact_body_bytes': True}


def test_get_download_file_path_uses_content_disposition():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')
    filename = 'github3.py-0.7.1-py2.py3-none-any.whl'
    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'})
        path = stream.get_download_file_path(r, None)
        r.close()
        assert path == filename

def test_get_download_file_path_directory():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')
    filename = 'github3.py-0.7.1-py2.py3-none-any.whl'
    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'})
        path = stream.get_download_file_path(r, tempfile.tempdir)
        r.close()
        assert path == os.path.join(tempfile.tempdir, filename)


def test_get_download_file_path_specific_file():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')
    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'})
        path = stream.get_download_file_path(r, '/arbitrary/file.path')
        r.close()
        assert path == '/arbitrary/file.path'


def test_stream_response_to_file_uses_content_disposition():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')
    filename = 'github3.py-0.7.1-py2.py3-none-any.whl'
    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'},
                  stream=True)
        stream.stream_response_to_file(r)

    assert os.path.exists(filename)
    os.unlink(filename)


def test_stream_response_to_specific_filename():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')
    filename = 'github3.py.whl'
    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'},
                  stream=True)
        stream.stream_response_to_file(r, path=filename)

    assert os.path.exists(filename)
    os.unlink(filename)


def test_stream_response_to_directory():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')

    td = tempfile.mkdtemp()
    try:
        filename = 'github3.py-0.7.1-py2.py3-none-any.whl'
        expected_path = os.path.join(td, filename)
        with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
            r = s.get(url, headers={'Accept': 'application/octet-stream'},
                      stream=True)
            stream.stream_response_to_file(r, path=td)

        assert os.path.exists(expected_path)
    finally:
        shutil.rmtree(td)


def test_stream_response_to_existing_file():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')
    filename = 'github3.py.whl'
    with open(filename, 'w') as f_existing:
        f_existing.write('test')

    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'},
                  stream=True)
    try:
        stream.stream_response_to_file(r, path=filename)
    except stream.exc.StreamingError as e:
        assert str(e).startswith('File already exists:')
    else:
        assert False, "Should have raised a FileExistsError"
    finally:
        os.unlink(filename)


def test_stream_response_to_file_like_object():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')
    file_obj = io.BytesIO()
    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'},
                  stream=True)
        stream.stream_response_to_file(r, path=file_obj)

    assert 0 < file_obj.tell()


def test_stream_response_to_file_chunksize():
    s = requests.Session()
    recorder = get_betamax(s)
    url = ('https://api.github.com/repos/sigmavirus24/github3.py/releases/'
           'assets/37944')

    class FileWrapper(io.BytesIO):
        def __init__(self):
            super(FileWrapper, self).__init__()
            self.chunk_sizes = []

        def write(self, data):
            self.chunk_sizes.append(len(data))
            return super(FileWrapper, self).write(data)

    file_obj = FileWrapper()

    chunksize = 1231

    with recorder.use_cassette('stream_response_to_file', **preserve_bytes):
        r = s.get(url, headers={'Accept': 'application/octet-stream'},
                  stream=True)
        stream.stream_response_to_file(r, path=file_obj, chunksize=chunksize)

    assert 0 < file_obj.tell()

    assert len(file_obj.chunk_sizes) >= 1
    assert file_obj.chunk_sizes[0] == chunksize


@pytest.fixture
def streamed_response(chunks=None):
    chunks = chunks or [b'chunk'] * 8
    response = mock.MagicMock()
    response.raw.stream.return_value = chunks
    return response


def test_tee(streamed_response):
    response = streamed_response
    expected_len = len('chunk') * 8
    fileobject = io.BytesIO()
    assert expected_len == sum(len(c) for c in tee.tee(response, fileobject))
    assert fileobject.getvalue() == b'chunkchunkchunkchunkchunkchunkchunkchunk'


def test_tee_rejects_StringIO():
    fileobject = io.StringIO()
    with pytest.raises(TypeError):
        # The generator needs to be iterated over before the exception will be
        # raised
        sum(len(c) for c in tee.tee(None, fileobject))


def test_tee_to_file(streamed_response):
    response = streamed_response
    expected_len = len('chunk') * 8
    assert expected_len == sum(
        len(c) for c in tee.tee_to_file(response, 'tee.txt')
        )
    assert os.path.exists('tee.txt')
    os.remove('tee.txt')


def test_tee_to_bytearray(streamed_response):
    response = streamed_response
    arr = bytearray()
    expected_arr = bytearray(b'chunk' * 8)
    expected_len = len(expected_arr)
    assert expected_len == sum(
        len(c) for c in tee.tee_to_bytearray(response, arr)
        )
    assert expected_arr == arr


def test_tee_to_bytearray_only_accepts_bytearrays():
    with pytest.raises(TypeError):
        tee.tee_to_bytearray(None, object())


class TrackedTarget(object):
    def __init__(self, name, failure_chunk=None):
        self.name = name
        self.failure_chunk = failure_chunk
        self.data = bytearray()
        self.closed = 0
        self.write_calls = 0

    @property
    def mode(self):
        return 'wb'

    def write(self, data):
        self.write_calls += 1
        should_fail = (
            self.failure_chunk is not None and
            self.write_calls == self.failure_chunk
        )
        if should_fail:
            raise IOError('target {} failed'.format(self.name))
        self.data.extend(data)
        return len(data)

    def close(self):
        self.closed += 1


class ShortWriteTarget(TrackedTarget):
    def __init__(self, name, failure_chunk):
        super(ShortWriteTarget, self).__init__(name, failure_chunk)

    def write(self, data):
        self.write_calls += 1
        if self.write_calls == self.failure_chunk:
            return 0
        self.data.extend(data)
        return len(data)


class FakeRaw(object):
    def __init__(self, chunks):
        self.chunks = chunks
        self.stream_calls = 0

    def stream(self, amt, decode_content=None):
        self.stream_calls += 1
        for chunk in self.chunks:
            yield chunk


class FakeResponse(object):
    def __init__(self, chunks):
        self.raw = FakeRaw(chunks)
        self.closed = 0

    def close(self):
        self.closed += 1


def _failing_fanout_response():
    return FakeResponse([b'one', b'two', b'three'])


def test_tee_to_targets_stop_on_first_failure():
    response = _failing_fanout_response()
    first_target = TrackedTarget('first')
    second_target = TrackedTarget('second', failure_chunk=2)
    receipt = tee.TeeReceipt()

    with pytest.raises(IOError, match='target second failed') as error:
        list(tee.tee_to_targets(
            response,
            {'first': first_target, 'second': second_target},
            chunksize=3,
            receipt=receipt,
        ))

    assert error.value is receipt.failures['second']
    assert bytes(first_target.data) == b'onetwo'
    assert bytes(second_target.data) == b'one'
    assert receipt.confirmed_bytes == {'first': 6, 'second': 3}
    assert response.raw.stream_calls == 1
    assert response.closed == 0
    assert first_target.closed == 0
    assert second_target.closed == 0


def test_tee_to_targets_continue_after_failure():
    response = _failing_fanout_response()
    first_target = TrackedTarget('first')
    second_target = TrackedTarget('second', failure_chunk=2)
    receipt = tee.TeeReceipt()

    consumed = list(tee.tee_to_targets(
        response,
        {'first': first_target, 'second': second_target},
        chunksize=3,
        receipt=receipt,
        on_target_failure=tee.CONTINUE_ON_FAILURE,
    ))

    assert consumed == [b'one', b'two', b'three']
    assert bytes(first_target.data) == b'onetwothree'
    assert bytes(second_target.data) == b'one'
    assert receipt.confirmed_bytes == {'first': 11, 'second': 3}
    assert isinstance(receipt.failures['second'], IOError)
    assert response.raw.stream_calls == 1
    assert response.closed == 0
    assert first_target.closed == 0
    assert second_target.closed == 0


def test_tee_to_targets_short_write_is_explicit_and_continue_policy_works():
    response = _failing_fanout_response()
    first_target = TrackedTarget('first')
    second_target = ShortWriteTarget('second', 2)
    receipt = tee.TeeReceipt()

    consumed = list(tee.tee_to_targets(
        response,
        [first_target, second_target],
        chunksize=3,
        receipt=receipt,
        on_target_failure=tee.CONTINUE_ON_FAILURE,
    ))

    assert consumed == [b'one', b'two', b'three']
    assert bytes(first_target.data) == b'onetwothree'
    assert bytes(second_target.data) == b'one'
    assert receipt.confirmed_bytes == {0: 11, 1: 3}
    assert isinstance(receipt.failures[1], OSError)
    assert 'short write' in str(receipt.failures[1])


def test_tee_to_targets_only_closes_failed_targets_when_requested():
    response = _failing_fanout_response()
    first_target = TrackedTarget('first')
    second_target = TrackedTarget('second', failure_chunk=2)
    receipt = tee.TeeReceipt()

    with pytest.raises(IOError):
        list(tee.tee_to_targets(
            response,
            {'first': first_target, 'second': second_target},
            chunksize=3,
            receipt=receipt,
            close_targets_on_failure=True,
        ))

    assert first_target.closed == 0
    assert second_target.closed == 1
    assert receipt.closed_targets == {'second'}
    assert response.closed == 0


def test_tee_to_targets_rejects_non_binary_target():
    response = _failing_fanout_response()
    target = mock.MagicMock()
    target.mode = 'w'

    with pytest.raises(TypeError):
        list(tee.tee_to_targets(response, {'text': target}))

    assert response.raw.stream_calls == 0


def test_tee_to_targets_rejects_invalid_failure_policy():
    response = _failing_fanout_response()
    target = TrackedTarget('first')

    with pytest.raises(ValueError):
        list(tee.tee_to_targets(
            response,
            [target],
            on_target_failure='unknown',
        ))

    assert response.raw.stream_calls == 0
    assert target.write_calls == 0


def test_tee_to_targets_requires_at_least_one_target():
    response = _failing_fanout_response()

    with pytest.raises(ValueError):
        list(tee.tee_to_targets(response, []))

    assert response.raw.stream_calls == 0


def test_tee_to_targets_rejects_invalid_receipt():
    response = _failing_fanout_response()
    target = TrackedTarget('first')

    with pytest.raises(TypeError):
        list(tee.tee_to_targets(response, [target], receipt={}))

    assert response.raw.stream_calls == 0
    assert target.write_calls == 0
    assert target.closed == 0


def test_tee_to_targets_accepts_none_write_result():
    response = FakeResponse([b'one'])

    class NoneWriter(TrackedTarget):
        def write(self, data):
            self.write_calls += 1
            self.data.extend(data)
            return None

    target = NoneWriter('first')
    receipt = tee.TeeReceipt()

    assert list(tee.tee_to_targets(response, [target], receipt=receipt)) == [
        b'one'
    ]
    assert receipt.confirmed_bytes == {0: 3}
    assert receipt.has_failures() is False
