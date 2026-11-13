.. _uploading-data:

Uploading Data
==============

Streaming Multipart Data Encoder
--------------------------------

Requests has `support for multipart uploads`_, but the API means that using
that functionality to build exactly the Multipart upload you want can be
difficult or impossible. Additionally, when using Requests' Multipart upload
functionality all the data must be read into memory before being sent to the
server. In extreme cases, this can make it impossible to send a file as part of
a ``multipart/form-data`` upload.

The toolbelt contains a class that allows you to build multipart request bodies
in exactly the format you need, and to avoid reading files into memory. An
example of how to use it is like this:

.. code-block:: python

    import requests
    from requests_toolbelt.multipart.encoder import MultipartEncoder

    m = MultipartEncoder(
        fields={'field0': 'value', 'field1': 'value',
                'field2': ('filename', open('file.py', 'rb'), 'text/plain')}
        )

    r = requests.post('http://httpbin.org/post', data=m,
                      headers={'Content-Type': m.content_type})

The :class:`~requests_toolbelt.multipart.encoder.MultipartEncoder` has the
``.to_string()`` convenience method, as well. This method renders the
multipart body into a string. This is useful when developing your code,
allowing you to confirm that the multipart body has the form you expect before
you send it on.

The toolbelt also provides a way to monitor your streaming uploads with
the :class:`~requests_toolbelt.multipart.encoder.MultipartEncoderMonitor`.

.. autoclass:: requests_toolbelt.multipart.encoder.MultipartEncoder

.. _support for multipart uploads: http://docs.python-requests.org/en/latest/user/quickstart/#post-a-multipart-encoded-file

Monitoring Your Streaming Multipart Upload
------------------------------------------

If you need to stream your ``multipart/form-data`` upload then you're probably
in the situation where it might take a while to upload the content. In these
cases, it might make sense to be able to monitor the progress of the upload.
For this reason, the toolbelt provides the
:class:`~requests_toolbelt.multipart.encoder.MultipartEncoderMonitor`. The
monitor wraps an instance of a
:class:`~requests_toolbelt.multipart.encoder.MultipartEncoder` and is used
exactly like the encoder. It provides a similar API with some additions:

- The monitor accepts a function as a callback. The function is called every
  time ``requests`` calls ``read`` on the monitor and passes in the monitor as
  an argument.

- The monitor tracks how many bytes have been read in the course of the
  upload.

You might use the monitor to create a progress bar for the upload. Here is `an
example using clint`_ which displays the progress bar.

To use the monitor you would follow a pattern like this:

.. code-block:: python

    import requests
    from requests_toolbelt.multipart import encoder

    def my_callback(monitor):
        # Your callback function
        pass

    e = encoder.MultipartEncoder(
        fields={'field0': 'value', 'field1': 'value',
                'field2': ('filename', open('file.py', 'rb'), 'text/plain')}
        )
    m = encoder.MultipartEncoderMonitor(e, my_callback)

    r = requests.post('http://httpbin.org/post', data=m,
                      headers={'Content-Type': m.content_type})

If you have a very simple use case you can also do:

.. code-block:: python

    import requests
    from requests_toolbelt.multipart.encoder import MultipartEncoderMonitor

    def my_callback(monitor):
        # Your callback function
        pass

    m = MultipartEncoderMonitor.from_fields(
        fields={'field0': 'value', 'field1': 'value',
                'field2': ('filename', open('file.py', 'rb'), 'text/plain')},
        callback=my_callback
        )

    r = requests.post('http://httpbin.org/post', data=m,
                      headers={'Content-Type': m.content_type})


.. autoclass:: requests_toolbelt.multipart.encoder.MultipartEncoderMonitor

.. _an example using clint:
    https://github.com/requests/toolbelt/blob/master/examples/monitor/progress_bar.py

Streaming Data from a Generator
-------------------------------

There are cases where you, the user, have a generator of some large quantity
of data and you already know the size of that data. If you pass the generator
to ``requests`` via the ``data`` parameter, ``requests`` will assume that you
want to upload the data in chunks and set a ``Transfer-Encoding`` header value
of ``chunked``. Often times, this causes the server to behave poorly. If you
want to avoid this, you can use the
:class:`~requests.toolbelt.streaming_iterator.StreamingIterator`.  You pass it
the size of the data and the generator.

.. code-block:: python

    import requests
    from requests_toolbelt.streaming_iterator import StreamingIterator

    generator = some_function()  # Create your generator
    size = some_function_size()  # Get your generator's size
    content_type = content_type()  # Get the content-type of the data

    streamer = StreamingIterator(size, generator)
    r = requests.post('https://httpbin.org/post', data=streamer,
                      headers={'Content-Type': content_type})

The streamer will handle your generator for you and buffer the data before
passing it to ``requests``.

.. versionchanged:: 0.4.0

    File-like objects can be passed instead of a generator.

If, for example, you need to upload data being piped into standard in, you
might otherwise do:

.. code-block:: python

    import requests
    import sys

    r = requests.post(url, data=sys.stdin)

This would stream the data but would use a chunked transfer-encoding. If
instead, you know the length of the data that is being sent to ``stdin`` and
you want to prevent the data from being uploaded in chunks, you can use the
:class:`~requests_toolbelt.streaming_iterator.StreamingIterator` to stream the
contents of the file without relying on chunking.

.. code-block:: python

    import requests
    from requests_toolbelt.streaming_iterator import StreamingIterator
    import sys

    stream = StreamingIterator(size, sys.stdin)
    r = requests.post(url, data=stream,
                      headers={'Content-Type': content_type})

.. autoclass:: requests_toolbelt.streaming_iterator.StreamingIterator

Replaying an Upload Body
------------------------

A :class:`~requests_toolbelt.streaming_iterator.StreamingIterator` wraps a
one-pass source: once it has been consumed, a second attempt at sending the
request can only transmit whatever bytes are left. Some proxies and servers
ask the client to resubmit a request after they have only read part of the
body, which makes this a real problem.

The
:class:`~requests_toolbelt.streaming_iterator.ReplayableStreamingIterator`
solves this without buffering the whole upload in memory. Instead of the
data itself, you hand it a callable that opens a fresh source of the same
data every time it is called:

.. code-block:: python

    import requests
    from requests_toolbelt import ReplayableStreamingIterator

    def reopen():
        return open('/tmp/collection-result.bin', 'rb')

    streamer = ReplayableStreamingIterator(size, reopen)
    r = requests.post(url, data=streamer)

The callable must return a binary file-like object with ``read`` and
``close`` methods, positioned at the first byte of the data. Before the
body is sent again, call ``streamer.reset()``: the source consumed so far
is closed and a new one is opened. The declared size of the new source is
checked against the original size, and the number of bytes actually read
from a source is accounted for when it ends. If a source cannot be
re-opened or no longer matches the declared length, a
:class:`~requests_toolbelt.exceptions.SourceNotReplayableError` explains
why instead of silently sending a truncated body. When you are done with
the body, call ``streamer.close()`` to release the source currently held.

.. autoclass:: requests_toolbelt.streaming_iterator.ReplayableStreamingIterator

Replaying a Multipart Body
--------------------------

The :class:`~requests_toolbelt.multipart.encoder.MultipartEncoder` can be
rewound as well, provided every part body can be replayed. Parts built from
plain strings or seekable files rewind themselves; a part whose value is a
:class:`~requests_toolbelt.streaming_iterator.ReplayableStreamingIterator`
re-opens its source; a part backed by a one-pass source (a generator, a
:class:`~requests_toolbelt.streaming_iterator.StreamingIterator`, a socket)
raises :class:`~requests_toolbelt.exceptions.SourceNotReplayableError` with
the concrete reason:

.. code-block:: python

    import requests
    from requests_toolbelt import (
        MultipartEncoder, ReplayableStreamingIterator,
        )

    streamer = ReplayableStreamingIterator(size, reopen)
    encoder = MultipartEncoder(
        fields={'file': ('collection.bin', streamer,
                         'application/octet-stream')}
        )

    r = requests.post(url, data=encoder,
                      headers={'Content-Type': encoder.content_type})
    if r.status_code == 409:  # proxy asks for the body again
        encoder.reset()
        r = requests.post(url, data=encoder,
                          headers={'Content-Type': encoder.content_type})
    encoder.close()

``encoder.reset()`` rewinds every part and the encoder's internal buffer,
so the next read returns the body from its first byte while ``encoder.len``
keeps reporting the same declared length. ``encoder.close()`` closes every
part body that can be closed, releasing the sources opened for the upload.
