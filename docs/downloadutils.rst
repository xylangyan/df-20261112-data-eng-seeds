.. _downloadutils:

Utilities for Downloading Streaming Responses
=============================================

.. autofunction::
    requests_toolbelt.downloadutils.stream.stream_response_to_file

.. autofunction::
    requests_toolbelt.downloadutils.tee.tee

.. autofunction::
    requests_toolbelt.downloadutils.tee.tee_to_targets

.. autofunction::
    requests_toolbelt.downloadutils.tee.tee_to_bytearray

.. autofunction::
    requests_toolbelt.downloadutils.tee.tee_to_file

.. autoclass:: requests_toolbelt.downloadutils.tee.TeeReceipt
    :members:

Receipts and failure policy
---------------------------

``tee_to_targets`` consumes ``response.raw`` exactly once, writes the same
chunks to each target, and yields those chunks to the caller. Passing a
:class:`~requests_toolbelt.downloadutils.tee.TeeReceipt` records the bytes
fully confirmed by each target and the first exception raised by a failed
target.

By default, one failed target stops the response. Pass
``on_target_failure=CONTINUE_ON_FAILURE`` to remove the failed target and
continue streaming to the others; call ``receipt.raise_for_failures()`` after
the loop when the accumulated failures must be surfaced. Short writes are
always treated as failures and reported as ``OSError``.

The caller owns the response and every file-like target it passes in.
``tee_to_targets`` never closes the response, and it closes a target only when
``close_targets_on_failure=True`` and that target's write failed. The original
``tee``, ``tee_to_file``, and ``tee_to_bytearray`` behavior is unchanged.
