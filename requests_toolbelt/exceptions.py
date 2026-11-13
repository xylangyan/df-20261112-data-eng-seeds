# -*- coding: utf-8 -*-
"""Collection of exceptions raised by requests-toolbelt."""


class StreamingError(Exception):
    """Used in :mod:`requests_toolbelt.downloadutils.stream`."""
    pass


class VersionMismatchError(Exception):
    """Used to indicate a version mismatch in the version of requests required.

    The feature in use requires a newer version of Requests to function
    appropriately but the version installed is not sufficient.
    """
    pass


class RequestsVersionTooOld(Warning):
    """Used to indicate that the Requests version is too old.

    If the version of Requests is too old to support a feature, we will issue
    this warning to the user.
    """
    pass


class SourceNotReplayableError(Exception):
    """Used to indicate that an upload body cannot be replayed.

    This is raised by
    :class:`requests_toolbelt.streaming_iterator.ReplayableStreamingIterator`
    when re-sending a request would require a fresh source of the data but the
    caller cannot provide one, or the re-opened source does not match the
    originally declared length. The message explains the concrete reason
    instead of silently truncating the upload.
    """
    pass
