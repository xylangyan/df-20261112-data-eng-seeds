"""Tee function implementations."""
import io

_DEFAULT_CHUNKSIZE = 65536
STOP_ON_FIRST_FAILURE = 'stop'
CONTINUE_ON_FAILURE = 'continue'

__all__ = [
    'CONTINUE_ON_FAILURE',
    'STOP_ON_FIRST_FAILURE',
    'TeeReceipt',
    'tee',
    'tee_to_file',
    'tee_to_targets',
    'tee_to_bytearray',
]


class TeeReceipt(object):
    """Track bytes confirmed by each tee destination."""

    def __init__(self, targets=None):
        self.confirmed_bytes = {}
        self.failures = {}
        self.closed_targets = set()
        if targets is not None:
            for name in targets:
                self.confirmed_bytes[name] = 0

    @property
    def total_confirmed_bytes(self):
        return sum(self.confirmed_bytes.values())

    @property
    def failed_targets(self):
        return set(self.failures)

    def has_failures(self):
        return bool(self.failures)

    def raise_for_failures(self):
        if self.failures:
            raise next(iter(self.failures.values()))

    def __repr__(self):
        return 'TeeReceipt(confirmed_bytes={!r}, failures={!r})'.format(
            self.confirmed_bytes, self.failures
        )


def _tee(response, callback, chunksize, decode_content):
    for chunk in response.raw.stream(amt=chunksize,
                                     decode_content=decode_content):
        callback(chunk)
        yield chunk


def _is_binary_file(fileobject):
    return (
        'b' in getattr(fileobject, 'mode', '')
        or isinstance(fileobject, io.BytesIO)
    )


def _normalize_targets(targets):
    if isinstance(targets, dict):
        return list(targets.items())

    if not isinstance(targets, (list, tuple)):
        raise TypeError('targets must be a dict, list, or tuple')

    normalized = []
    for index, target in enumerate(targets):
        if isinstance(target, tuple) and len(target) == 2:
            normalized.append(target)
        else:
            normalized.append((index, target))
    return normalized


def _validate_targets(normalized_targets):
    names = set()
    for name, target in normalized_targets:
        if not callable(getattr(target, 'write', None)):
            raise TypeError(
                'target {!r} must have a callable write method'.format(name)
            )
        if not _is_binary_file(target):
            raise TypeError(
                'tee_to_targets() will write bytes directly to {!r}, it must '
                'be opened with the "b" flag if it is a file or inherit from '
                'io.BytesIO.'.format(name)
            )
        if name in names:
            raise ValueError('duplicate target name: {!r}'.format(name))
        names.add(name)


def _write_to_targets(chunk, targets, receipt, on_target_failure,
                      close_targets):
    for name, target in list(targets):
        try:
            written = target.write(chunk)
            if written is None:
                written = len(chunk)
            if (not isinstance(written, int) or isinstance(written, bool) or
                    written < 0 or written > len(chunk)):
                raise OSError(
                    'target {!r} returned an invalid write count: {!r}'
                    .format(name, written)
                )
            if written != len(chunk):
                raise OSError(
                    'short write for target {!r}: expected {}, received {}'
                    .format(name, len(chunk), written)
                )
        except Exception as error:
            receipt.failures.setdefault(name, error)
            if close_targets and hasattr(target, 'close'):
                try:
                    target.close()
                except Exception as close_error:
                    receipt.failures.setdefault(name, close_error)
                finally:
                    receipt.closed_targets.add(name)
            targets.remove((name, target))
            if on_target_failure == STOP_ON_FIRST_FAILURE:
                return False
            continue
        receipt.confirmed_bytes[name] += len(chunk)
    return True


def tee_to_targets(response, targets, chunksize=_DEFAULT_CHUNKSIZE,
                   decode_content=None, receipt=None,
                   on_target_failure=STOP_ON_FIRST_FAILURE,
                   close_targets_on_failure=False):
    """Stream one response body to multiple write targets.

    The response body is iterated exactly once. Every destination receives the
    same chunks while the generator yields each chunk to its caller.

    ``receipt`` may be a :class:`TeeReceipt` instance. When provided, it is
    updated in place with the number of bytes fully confirmed by each target
    and with the first exception raised by that target.

    Pass ``on_target_failure=CONTINUE_ON_FAILURE`` to remove a failed target
    and continue streaming to the remaining targets. The default
    ``STOP_ON_FIRST_FAILURE`` keeps the old tee behavior of terminating the
    response iteration when a target cannot accept a chunk.

    Targets passed in by the caller are not closed on success. When
    ``close_targets_on_failure`` is true, only targets that fail while this
    generator owns the stream are closed. The response is never closed by this
    function; the caller owns its lifecycle.

    :param response: Response from requests.
    :type response: requests.Response
    :param targets: Mapping or sequence of writable binary file-like targets.
        A sequence of ``(name, target)`` pairs may also be supplied.
    :param int chunksize: (optional), Size of chunk to attempt to stream.
    :param bool decode_content: (optional), If True, this will decode the
        compressed content of the response.
    :param TeeReceipt receipt: (optional), Receipt updated with confirmed
        bytes and target failures.
    :param str on_target_failure: (optional), Either
        ``STOP_ON_FIRST_FAILURE`` or ``CONTINUE_ON_FAILURE``.
    :param bool close_targets_on_failure: (optional), Close a target when its
        write fails. Defaults to False because the caller owns passed-in
        targets.
    :raises: OSError when a target performs a short write. The original target
        exception is raised by the stop policy.
    """
    if on_target_failure not in (
            STOP_ON_FIRST_FAILURE, CONTINUE_ON_FAILURE):
        raise ValueError('invalid on_target_failure: {!r}'.format(
            on_target_failure
        ))

    normalized_targets = _normalize_targets(targets)
    if not normalized_targets:
        raise ValueError('at least one target is required')
    _validate_targets(normalized_targets)

    if receipt is None:
        receipt = TeeReceipt()
    elif not isinstance(receipt, TeeReceipt):
        raise TypeError('receipt must be a TeeReceipt instance')

    for name, target in normalized_targets:
        receipt.confirmed_bytes.setdefault(name, 0)
        receipt.failures.pop(name, None)

    active_targets = list(normalized_targets)
    for chunk in response.raw.stream(amt=chunksize,
                                     decode_content=decode_content):
        should_continue = _write_to_targets(
            chunk, active_targets, receipt, on_target_failure,
            close_targets_on_failure
        )
        if not should_continue:
            receipt.raise_for_failures()
        yield chunk

    if on_target_failure == STOP_ON_FIRST_FAILURE:
        receipt.raise_for_failures()


def tee(response, fileobject, chunksize=_DEFAULT_CHUNKSIZE,
        decode_content=None):
    """Stream the response both to the generator and a file.

    This will stream the response body while writing the bytes to
    ``fileobject``.

    Example usage:

    .. code-block:: python

        resp = requests.get(url, stream=True)
        with open('save_file', 'wb') as save_file:
            for chunk in tee(resp, save_file):
                # do stuff with chunk

    .. code-block:: python

        import io

        resp = requests.get(url, stream=True)
        fileobject = io.BytesIO()

        for chunk in tee(resp, fileobject):
            # do stuff with chunk

    :param response: Response from requests.
    :type response: requests.Response
    :param fileobject: Writable file-like object.
    :type fileobject: file, io.BytesIO
    :param int chunksize: (optional), Size of chunk to attempt to stream.
    :param bool decode_content: (optional), If True, this will decode the
        compressed content of the response.
    :raises: TypeError if the fileobject wasn't opened with the right mode
        or isn't a BytesIO object.
    """
    if not _is_binary_file(fileobject):
        raise TypeError('tee() will write bytes directly to this fileobject'
                        ', it must be opened with the "b" flag if it is a file'
                        ' or inherit from io.BytesIO.')

    return _tee(response, fileobject.write, chunksize, decode_content)


def tee_to_file(response, filename, chunksize=_DEFAULT_CHUNKSIZE,
                decode_content=None):
    """Stream the response both to the generator and a file.

    This will open a file named ``filename`` and stream the response body
    while writing the bytes to the opened file object.

    Example usage:

    .. code-block:: python

        resp = requests.get(url, stream=True)
        for chunk in tee_to_file(resp, 'save_file'):
            # do stuff with chunk

    :param response: Response from requests.
    :type response: requests.Response
    :param str filename: Name of file in which we write the response content.
    :param int chunksize: (optional), Size of chunk to attempt to stream.
    :param bool decode_content: (optional), If True, this will decode the
        compressed content of the response.
    """
    with open(filename, 'wb') as fd:
        for chunk in tee(response, fd, chunksize, decode_content):
            yield chunk


def tee_to_bytearray(response, bytearr, chunksize=_DEFAULT_CHUNKSIZE,
                     decode_content=None):
    """Stream the response both to the generator and a bytearray.

    This will stream the response provided to the function, add them to the
    provided :class:`bytearray` and yield them to the user.

    .. note::

        This uses the :meth:`bytearray.extend` by default instead of passing
        the bytearray into the ``readinto`` method.

    Example usage:

    .. code-block:: python

        b = bytearray()
        resp = requests.get(url, stream=True)
        for chunk in tee_to_bytearray(resp, b):
            # do stuff with chunk

    :param response: Response from requests.
    :type response: requests.Response
    :param bytearray bytearr: Array to add the streamed bytes to.
    :param int chunksize: (optional), Size of chunk to attempt to stream.
    :param bool decode_content: (optional), If True, this will decode the
        compressed content of the response.
    """
    if not isinstance(bytearr, bytearray):
        raise TypeError('tee_to_bytearray() expects bytearr to be a '
                        'bytearray')
    return _tee(response, bytearr.extend, chunksize, decode_content)
