# -*- coding: utf-8 -*-
"""

requests_toolbelt.streaming_iterator
====================================

This holds the implementation details for the :class:`StreamingIterator`. It
is designed for the case where you, the user, know the size of the upload but
need to provide the data as an iterator. This class will allow you to specify
the size and stream the data without using a chunked transfer-encoding.

"""
from requests.utils import super_len

from .exceptions import SourceNotReplayableError
from .multipart.encoder import (
    CustomBytesIO, encode_with, total_len
    )


class StreamingIterator(object):

    """
    This class provides a way of allowing iterators with a known size to be
    streamed instead of chunked.

    In requests, if you pass in an iterator it assumes you want to use
    chunked transfer-encoding to upload the data, which not all servers
    support well. Additionally, you may want to set the content-length
    yourself to avoid this but that will not work. The only way to preempt
    requests using a chunked transfer-encoding and forcing it to stream the
    uploads is to mimic a very specific interace. Instead of having to know
    these details you can instead just use this class. You simply provide the
    size and iterator and pass the instance of StreamingIterator to requests
    via the data parameter like so:

    .. code-block:: python

        from requests_toolbelt import StreamingIterator

        import requests

        # Let iterator be some generator that you already have and size be
        # the size of the data produced by the iterator

        r = requests.post(url, data=StreamingIterator(size, iterator))

    You can also pass file-like objects to :py:class:`StreamingIterator` in
    case requests can't determize the filesize itself. This is the case with
    streaming file objects like ``stdin`` or any sockets. Wrapping e.g. files
    that are on disk with ``StreamingIterator`` is unnecessary, because
    requests can determine the filesize itself.

    Naturally, you should also set the `Content-Type` of your upload
    appropriately because the toolbelt will not attempt to guess that for you.
    """

    def __init__(self, size, iterator, encoding='utf-8'):
        #: The expected size of the upload
        self.size = int(size)

        if self.size < 0:
            raise ValueError(
                'The size of the upload must be a positive integer'
                )

        #: Attribute that requests will check to determine the length of the
        #: body. See bug #80 for more details
        self.len = self.size

        #: Encoding the input data is using
        self.encoding = encoding

        #: The iterator used to generate the upload data
        self.iterator = iterator

        if hasattr(iterator, 'read'):
            self._file = iterator
        else:
            self._file = _IteratorAsBinaryFile(iterator, encoding)

    def read(self, size=-1):
        return encode_with(self._file.read(size), self.encoding)


class _IteratorAsBinaryFile(object):
    def __init__(self, iterator, encoding='utf-8'):
        #: The iterator used to generate the upload data
        self.iterator = iterator

        #: Encoding the iterator is using
        self.encoding = encoding

        # The buffer we use to provide the correct number of bytes requested
        # during a read
        self._buffer = CustomBytesIO()

    def _get_bytes(self):
        try:
            return encode_with(next(self.iterator), self.encoding)
        except StopIteration:
            return b''

    def _load_bytes(self, size):
        self._buffer.smart_truncate()
        amount_to_load = size - super_len(self._buffer)
        bytes_to_append = True

        while amount_to_load > 0 and bytes_to_append:
            bytes_to_append = self._get_bytes()
            amount_to_load -= self._buffer.append(bytes_to_append)

    def read(self, size=-1):
        size = int(size)
        if size == -1:
            return b''.join(self.iterator)

        self._load_bytes(size)
        return self._buffer.read(size)


class ReplayableStreamingIterator(object):
    """A :class:`StreamingIterator`-compatible body that can be replayed.

    A regular :class:`StreamingIterator` wraps a one-pass source: once the
    underlying file or iterator has been consumed, a second attempt at
    uploading the body can only send whatever bytes are left. When a proxy
    asks a client to resubmit a request it has only read half of, that
    produces a truncated body.

    This class never buffers the whole upload in memory. Instead the caller
    supplies ``reopen``: a callable that opens a fresh, position-zero,
    binary file-like object for the same data every time it is called::

        def reopen():
            return open('/tmp/collection-result.bin', 'rb')

        streamer = ReplayableStreamingIterator(size, reopen)
        r = requests.post(url, data=streamer)

    The object returned by ``reopen`` must expose ``read(size)`` and
    ``close()``. Each opened source is closed when it is replaced or when
    :meth:`close` is called, so reopening never leaks file descriptors.

    The declared size of every re-opened source is checked against the
    original size and the number of bytes actually produced by a source
    before it is closed. A mismatch means the callable no longer serves the
    same data and raises :class:`SourceNotReplayableError` instead of
    silently sending a body whose ``Content-Length`` lies.
    """

    def __init__(self, size, reopen, encoding='utf-8'):
        #: The expected size of the upload
        self.size = int(size)

        if self.size < 0:
            raise ValueError(
                'The size of the upload must be a positive integer'
                )

        if not callable(reopen):
            raise TypeError(
                'The reopen argument must be a callable that opens a fresh '
                'file-like object positioned at the start of the data'
                )

        #: Encoding the input data is using
        self.encoding = encoding

        #: Callable used to open a brand new source for the same data
        self.reopen = reopen

        #: The source currently being read
        self._file = None

        #: Number of bytes read from the current source
        self._bytes_read = 0

        #: Whether the current attempt has been read to its end
        self._finished = False

    @property
    def len(self):
        """Bytes still to be read from the current source.

        ``total_len`` (and :class:`~requests_toolbelt.multipart.encoder.Part`)
        use this to tell when the body is exhausted. The full, declared
        upload size is kept on :attr:`size` and does not change between
        attempts.
        """
        return self.size - self._bytes_read

    def _open_source(self):
        """Open a new source via the user-provided callable."""
        try:
            source = self.reopen()
        except SourceNotReplayableError:
            raise
        except Exception as exc:
            raise SourceNotReplayableError(
                'The reopen callable failed to open a fresh source: '
                '{0}'.format(exc)
                )

        if not hasattr(source, 'read'):
            raise SourceNotReplayableError(
                'The reopen callable must return a file-like object with a '
                'read method, got {0!r} instead'.format(source)
                )
        if not hasattr(source, 'close'):
            raise SourceNotReplayableError(
                'The object returned by the reopen callable has no close '
                'method, so it cannot be released between attempts: '
                '{0!r}'.format(source)
                )

        return source

    def _verify_size(self, source):
        """Make sure a re-opened source still advertises the same size."""
        source_size = total_len(source)
        if source_size is not None and source_size != self.size:
            raise SourceNotReplayableError(
                'A re-opened source advertises a length of {0} but the '
                'upload body was declared to be {1} bytes long'.format(
                    source_size, self.size)
                )

    def _close_source(self):
        """Close the source currently in use, if any."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def reset(self):
        """Rewind the body so the next read starts at the first byte.

        The source consumed so far is closed and a fresh one is opened
        through the ``reopen`` callable. This is the hook
        :class:`~requests_toolbelt.multipart.encoder.MultipartEncoder`
        uses when a part backed by this object has to be replayed.
        """
        self._close_source()
        self._bytes_read = 0
        self._finished = False
        self._file = self._open_source()
        self._verify_size(self._file)

    def close(self):
        """Release the source currently held by this body."""
        self._close_source()
        self._bytes_read = 0
        self._finished = False

    def read(self, size=-1):
        """Read at most ``size`` bytes from the current source.

        A bounded ``size`` (the way httplib drives uploads) only reads from
        the open source and never buffers the whole body. When a source is
        exhausted, the bytes it actually produced are accounted for and the
        source is closed. Reading past the end returns ``b''`` until
        :meth:`reset` starts a new attempt.
        """
        if self._finished:
            return b''

        if self._file is None:
            self.reset()

        chunk = encode_with(self._file.read(size), self.encoding)
        self._bytes_read += len(chunk)

        if self._bytes_read > self.size:
            raise SourceNotReplayableError(
                'The source produced more than the declared {0} bytes of '
                'the upload body; it cannot be replayed with the advertised'
                ' length'.format(self.size)
                )

        if not chunk and self._bytes_read != self.size:
            raise SourceNotReplayableError(
                'The source ended after {0} bytes but the upload body was '
                'declared to be {1} bytes long; the source cannot be replayed'
                ' with the advertised length'.format(
                    self._bytes_read, self.size)
                )

        if not chunk:
            self._close_source()
            self._finished = True

        return chunk
