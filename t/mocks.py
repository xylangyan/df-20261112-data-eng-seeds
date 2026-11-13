from __future__ import annotations

import time
from itertools import count
from typing import TYPE_CHECKING
from unittest.mock import Mock

from kombu.exceptions import OperationalError
from kombu.transport import base
from kombu.utils import json

if TYPE_CHECKING:
    from types import TracebackType


class _ContextMock(Mock):
    """Dummy class implementing __enter__ and __exit__
    as the :keyword:`with` statement requires these to be implemented
    in the class, not just the instance."""

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None
    ) -> None:
        pass


def ContextMock(*args, **kwargs):
    """Mock that mocks :keyword:`with` statement contexts."""
    obj = _ContextMock(*args, **kwargs)
    obj.attach_mock(_ContextMock(), '__enter__')
    obj.attach_mock(_ContextMock(), '__exit__')
    obj.__enter__.return_value = obj
    # if __exit__ return a value the exception is ignored,
    # so it must return None here.
    obj.__exit__.return_value = None
    return obj


def PromiseMock(*args, **kwargs):
    m = Mock(*args, **kwargs)

    def on_throw(exc=None, *args, **kwargs):
        if exc:
            raise exc
        raise
    m.throw.side_effect = on_throw
    m.set_error_state.side_effect = on_throw
    m.throw1.side_effect = on_throw
    return m


class MockPool:

    def __init__(self, value=None):
        self.value = value or ContextMock()

    def acquire(self, **kwargs):
        return self.value


class Message(base.Message):

    def __init__(self, *args, **kwargs):
        self.throw_decode_error = kwargs.get('throw_decode_error', False)
        super().__init__(*args, **kwargs)

    def decode(self):
        if self.throw_decode_error:
            raise ValueError("can't decode message")
        return super().decode()


class Channel(base.StdChannel):
    open = True
    throw_decode_error = False
    _ids = count(1)

    def __init__(self, connection):
        self.connection = connection
        self.called = []
        self.deliveries = count(1)
        self.to_deliver = []
        self.events = {'basic_return': set()}
        self.channel_id = next(self._ids)

    def _called(self, name):
        self.called.append(name)

    def __contains__(self, key):
        return key in self.called

    def exchange_declare(self, *args, **kwargs):
        self._called('exchange_declare')

    def prepare_message(self, body, priority=0, content_type=None,
                        content_encoding=None, headers=None, properties={}):
        self._called('prepare_message')
        return {'body': body,
                'headers': headers,
                'properties': properties,
                'priority': priority,
                'content_type': content_type,
                'content_encoding': content_encoding}

    def basic_publish(self, message, exchange='', routing_key='',
                      mandatory=False, immediate=False, **kwargs):
        self._called('basic_publish')
        return message, exchange, routing_key

    def exchange_delete(self, *args, **kwargs):
        self._called('exchange_delete')

    def queue_declare(self, *args, **kwargs):
        self._called('queue_declare')

    def queue_bind(self, *args, **kwargs):
        self._called('queue_bind')

    def queue_unbind(self, *args, **kwargs):
        self._called('queue_unbind')

    def queue_delete(self, queue, if_unused=False, if_empty=False, **kwargs):
        self._called('queue_delete')

    def basic_get(self, *args, **kwargs):
        self._called('basic_get')
        try:
            return self.to_deliver.pop()
        except IndexError:
            pass

    def queue_purge(self, *args, **kwargs):
        self._called('queue_purge')

    def basic_consume(self, *args, **kwargs):
        self._called('basic_consume')

    def basic_cancel(self, *args, **kwargs):
        self._called('basic_cancel')

    def basic_ack(self, *args, **kwargs):
        self._called('basic_ack')

    def basic_recover(self, requeue=False):
        self._called('basic_recover')

    def exchange_bind(self, *args, **kwargs):
        self._called('exchange_bind')

    def exchange_unbind(self, *args, **kwargs):
        self._called('exchange_unbind')

    def close(self):
        self._called('close')

    def message_to_python(self, message, *args, **kwargs):
        self._called('message_to_python')
        return Message(body=json.dumps(message),
                       channel=self,
                       delivery_tag=next(self.deliveries),
                       throw_decode_error=self.throw_decode_error,
                       content_type='application/json',
                       content_encoding='utf-8')

    def flow(self, active):
        self._called('flow')

    def basic_reject(self, delivery_tag, requeue=False):
        if requeue:
            return self._called('basic_reject:requeue')
        return self._called('basic_reject')

    def basic_qos(self, prefetch_size=0, prefetch_count=0,
                  apply_global=False):
        self._called('basic_qos')


class Connection:
    connected = True

    def __init__(self, client):
        self.client = client

    def channel(self):
        return Channel(self)


class Transport(base.Transport):

    def establish_connection(self):
        return Connection(self.client)

    def create_channel(self, connection):
        return connection.channel()

    def drain_events(self, connection, **kwargs):
        return 'event'

    def close_connection(self, connection):
        connection.connected = False


class RecordingChannel(base.StdChannel):
    """Channel double recording every operation, with injectable failures.

    Each instance keeps its own ordered ``calls`` log and its own
    declaration cache (``_declared_entities``), mirroring how a real
    transport channel scopes declarations to a single channel.  Use
    :meth:`fail_next` to make the next matching operation raise, e.g. to
    simulate a connection drop mid-declaration.
    """
    _ids = count(1)

    def __init__(self, connection):
        self.connection = connection
        self.channel_id = next(self._ids)
        self.calls = []
        self.events = {'basic_return': set()}
        self._declared_entities = set()
        self._failures = []

    def fail_next(self, op, error):
        """Raise ``error`` the next time operation ``op`` is invoked."""
        self._failures.append((op, error))

    def _record(self, op, *args):
        self.calls.append((op, args))
        for index, (failed_op, error) in enumerate(self._failures):
            if failed_op == op:
                del self._failures[index]
                raise error

    def ops(self):
        return [op for op, _ in self.calls]

    def count(self, op):
        return self.ops().count(op)

    def exchange_declare(self, exchange=None, **kwargs):
        self._record('exchange_declare', exchange)

    def queue_declare(self, queue=None, **kwargs):
        self._record('queue_declare', queue)
        return queue, 0, 0

    def queue_bind(self, queue=None, exchange=None, routing_key='',
                   **kwargs):
        self._record('queue_bind', queue, exchange, routing_key)

    def prepare_message(self, body, priority=0, content_type=None,
                        content_encoding=None, headers=None, properties=None):
        return {'body': body, 'properties': properties or {}}

    def basic_publish(self, message, exchange='', routing_key='', **kwargs):
        self._record('basic_publish', exchange, routing_key)

    def close(self):
        self._record('close')


class RecordingBrokerConnection:
    """In-process broker connection whose channels record their calls."""
    connected = True

    def __init__(self, client):
        self.client = client

    def channel(self):
        return self.client.transport.make_channel(self)


class RecordingTransport(base.Transport):
    """Transport producing :class:`RecordingChannel` instances.

    Connection drops are surfaced as recoverable connection errors so the
    :meth:`kombu.Connection.ensure` retry machinery reconnects and revives
    the producer onto a fresh channel.
    """
    recoverable_connection_errors = (OperationalError,)
    recoverable_channel_errors = ()
    connection_errors = (OperationalError,)
    channel_errors = ()

    def __init__(self, *args, **kwargs):
        self.channel_failures = []
        self.channels = []
        super().__init__(*args, **kwargs)

    def fail_new_channels(self, op, error):
        """Make every channel created from now on fail operation ``op``."""
        self.channel_failures.append((op, error))

    def make_channel(self, connection):
        channel = RecordingChannel(connection)
        for op, error in self.channel_failures:
            channel.fail_next(op, error)
        self.channels.append(channel)
        return channel

    def establish_connection(self):
        return RecordingBrokerConnection(self.client)

    def create_channel(self, connection):
        return self.make_channel(connection)

    def close_connection(self, connection):
        connection.connected = False

    def drain_events(self, connection, **kwargs):
        return 'event'


class TimeoutingTransport(Transport):
    recoverable_connection_errors = (TimeoutError,)

    def __init__(self, connect_timeout=1, **kwargs):
        self.connect_timeout = connect_timeout
        super().__init__(**kwargs)

    def establish_connection(self):
        time.sleep(self.connect_timeout)
        raise TimeoutError('timed out')
