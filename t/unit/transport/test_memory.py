from __future__ import annotations

import socket

import pytest

from kombu import Connection, Consumer, Exchange, Producer, Queue
from kombu.transport import virtual
from kombu.utils.uuid import uuid


class test_MemoryTransport:

    def setup_method(self):
        self.c = Connection(transport='memory')
        self.e = Exchange('test_transport_memory')
        self.q = Queue('test_transport_memory',
                       exchange=self.e,
                       routing_key='test_transport_memory')
        self.q2 = Queue('test_transport_memory2',
                        exchange=self.e,
                        routing_key='test_transport_memory2')
        self.fanout = Exchange('test_transport_memory_fanout', type='fanout')
        self.q3 = Queue('test_transport_memory_fanout1',
                        exchange=self.fanout)
        self.q4 = Queue('test_transport_memory_fanout2',
                        exchange=self.fanout)

    def test_driver_version(self):
        assert self.c.transport.driver_version()

    def test_produce_consume_noack(self):
        channel = self.c.channel()
        producer = Producer(channel, self.e)
        consumer = Consumer(channel, self.q, no_ack=True)

        for i in range(10):
            producer.publish({'foo': i}, routing_key='test_transport_memory')

        _received = []

        def callback(message_data, message):
            _received.append(message)

        consumer.register_callback(callback)
        consumer.consume()

        while 1:
            if len(_received) == 10:
                break
            self.c.drain_events()

        assert len(_received) == 10

    def test_produce_consume_fanout(self):
        producer = self.c.Producer()
        consumer = self.c.Consumer([self.q3, self.q4])

        producer.publish(
            {'hello': 'world'},
            declare=consumer.queues,
            exchange=self.fanout,
        )

        assert self.q3(self.c).get().payload == {'hello': 'world'}
        assert self.q4(self.c).get().payload == {'hello': 'world'}
        assert self.q3(self.c).get() is None
        assert self.q4(self.c).get() is None

    def test_produce_consume(self):
        channel = self.c.channel()
        producer = Producer(channel, self.e)
        consumer1 = Consumer(channel, self.q)
        consumer2 = Consumer(channel, self.q2)
        self.q2(channel).declare()

        for i in range(10):
            producer.publish({'foo': i}, routing_key='test_transport_memory')
        for i in range(10):
            producer.publish({'foo': i}, routing_key='test_transport_memory2')

        _received1 = []
        _received2 = []

        def callback1(message_data, message):
            _received1.append(message)
            message.ack()

        def callback2(message_data, message):
            _received2.append(message)
            message.ack()

        consumer1.register_callback(callback1)
        consumer2.register_callback(callback2)

        consumer1.consume()
        consumer2.consume()

        while 1:
            if len(_received1) + len(_received2) == 20:
                break
            self.c.drain_events()

        assert len(_received1) + len(_received2) == 20

        # compression
        producer.publish({'compressed': True},
                         routing_key='test_transport_memory',
                         compression='zlib')
        m = self.q(channel).get()
        assert m.payload == {'compressed': True}

        # queue.delete
        for i in range(10):
            producer.publish({'foo': i}, routing_key='test_transport_memory')
        assert self.q(channel).get()
        self.q(channel).delete()
        self.q(channel).declare()
        assert self.q(channel).get() is None

        # queue.purge
        for i in range(10):
            producer.publish({'foo': i}, routing_key='test_transport_memory2')
        assert self.q2(channel).get()
        self.q2(channel).purge()
        assert self.q2(channel).get() is None

    def test_drain_events(self):
        with pytest.raises(socket.timeout):
            self.c.drain_events(timeout=0.1)

        c1 = self.c.channel()
        c2 = self.c.channel()

        with pytest.raises(socket.timeout):
            self.c.drain_events(timeout=0.1)

        del c1  # so pyflakes doesn't complain.
        del c2

    def test_drain_events_unregistered_queue(self):
        c1 = self.c.channel()
        producer = self.c.Producer()
        consumer = self.c.Consumer([self.q2])

        producer.publish(
            {'hello': 'world'},
            declare=consumer.queues,
            routing_key=self.q2.routing_key,
            exchange=self.q2.exchange,
        )
        message = consumer.queues[0].get()._raw

        class Cycle:

            def get(self, callback, timeout=None):
                return (message, 'foo'), c1

        self.c.transport.cycle = Cycle()
        self.c.drain_events()

    def test_queue_for(self):
        chan = self.c.channel()
        chan.queues.clear()

        x = chan._queue_for('foo')
        assert x
        assert chan._queue_for('foo') is x

    # see the issue
    # https://github.com/celery/kombu/issues/1050
    def test_producer_on_return(self):
        def on_return(_exception, _exchange, _routing_key, _message):
            pass
        channel = self.c.channel()
        producer = Producer(channel, on_return=on_return)
        consumer = self.c.Consumer([self.q3])

        producer.publish(
            {'hello': 'on return'},
            declare=consumer.queues,
            exchange=self.fanout,
        )

        assert self.q3(self.c).get().payload == {'hello': 'on return'}
        assert self.q3(self.c).get() is None


class test_MemoryTransportRoundRobin:
    """Drain record for the opt-in ``round_robin`` queue order strategy.

    Queue ``a`` keeps a sustained backlog while a single message arrives on
    queue ``b`` part-way through draining. The record below captures, for
    every drain, the round, the queue served, and the number of
    unacknowledged messages immediately before the ack. It is the artifact
    used to check *where* ``b`` shows up and that the prefetch budget is
    never exceeded. No sleeps are involved: rounds are counted from the
    cycle cursor.
    """

    prefetch_count = 2

    def setup_method(self):
        # the memory transport keeps queues in process-wide class state, so
        # give every test its own queue names
        suffix = uuid()
        self.queue_a = 'a-' + suffix
        self.queue_b = 'b-' + suffix
        self.c = Connection(
            transport='memory',
            transport_options={'queue_order_strategy': 'round_robin'},
        )
        self.channel = self.c.channel()
        self.extra_channels = []
        for queue in (self.queue_a, self.queue_b):
            self.channel.queue_declare(queue)
        self.record = []

    def teardown_method(self):
        for channel in [self.channel] + self.extra_channels:
            if channel._qos is not None:
                channel._qos._on_collect.cancel()

    def new_channel(self):
        channel = self.c.channel()
        self.extra_channels.append(channel)
        return channel

    def publish(self, queue, body):
        self.channel.basic_publish(
            self.channel.prepare_message(body), '', queue)

    def consume(self, queue):
        self.channel.basic_consume(
            queue, False, callback=lambda *args: None,
            consumer_tag=uuid())
        self.channel.basic_qos(
            prefetch_count=self.prefetch_count)

    def drain(self):
        """Drain once and append a record entry for the message received."""
        self.channel.drain_events()
        state = self.channel.qos
        message = next(reversed(state._delivered.values()))
        routing_key = message.delivery_info['routing_key']
        self.record.append({
            'round': self.channel.cycle.pos,
            'queue': 'a' if routing_key == self.queue_a else 'b',
            'body': message.body.decode(),
            'unacked_before_ack': len(state._delivered) - len(state._dirty),
        })
        self.channel.basic_ack(message.delivery_tag)
        return self.record[-1]

    def test_b_appears_within_second_round_and_unacked_budget_holds(self):
        for i in range(8):
            self.publish(self.queue_a, 'a%d' % i)
        self.consume(self.queue_a)
        self.consume(self.queue_b)

        # drain part of the a backlog, then queue b mid-flight
        for _ in range(3):
            self.drain()
        self.publish(self.queue_b, 'b0')
        for _ in range(4):
            self.drain()

        queues = [entry['queue'] for entry in self.record]
        assert queues == ['a', 'a', 'a', 'b', 'a', 'a', 'a']
        # b is served on the first drain after it was published, i.e. in
        # round 2 at the latest even when a stays saturated.
        assert queues.index('b') <= 3 + 1
        # per-queue FIFO: a bodies are in publish order, b is untouched
        a_bodies = [e['body'] for e in self.record if e['queue'] == 'a']
        assert a_bodies == ['a0', 'a1', 'a2', 'a3', 'a4', 'a5']
        # the channel never holds more unacked messages than prefetch_count
        assert max(e['unacked_before_ack'] for e in self.record) \
            <= self.prefetch_count
        # drain records are append-only and acked in order
        assert [e['unacked_before_ack'] for e in self.record] == \
            [1, 1, 1, 1, 1, 1, 1]

    def test_full_queue_is_skipped_then_rejoins_after_ack(self):
        for i in range(6):
            self.publish(self.queue_a, 'a%d' % i)
        for i in range(3):
            self.publish(self.queue_b, 'b%d' % i)
        self.consume(self.queue_a)
        self.consume(self.queue_b)

        # no ack for the first two messages on each queue: prefetch is full,
        # so draining must raise Empty instead of exceeding the budget.
        self.channel.basic_qos(prefetch_count=2)
        first = self.channel.basic_get(self.queue_a)
        second = self.channel.basic_get(self.queue_b)
        assert first and second
        with pytest.raises(virtual.Empty):
            self.channel.drain_events()

        # one ack reopens exactly one slot and b, skipped while full, is
        # reachable again in the same rotation
        self.channel.basic_ack(first.delivery_tag)
        third = self.channel.basic_get(self.queue_b)
        assert third and third.body == b'b1'
        self.channel.basic_ack(second.delivery_tag)
        self.channel.basic_ack(third.delivery_tag)

    def test_slow_channel_does_not_consume_another_channels_budget(self):
        # QoS state lives on each channel, so a slow channel filling its own
        # unacked budget cannot change another channel's prefetch cap.
        blocked = self.new_channel()
        healthy = self.new_channel()
        slow_queue = 'slow-' + uuid()
        fast_queue = 'fast-' + uuid()
        for queue in (slow_queue, fast_queue):
            blocked.queue_declare(queue)
        for i in range(3):
            blocked.basic_publish(
                blocked.prepare_message('slow%d' % i), '', slow_queue)
        for i in range(3):
            blocked.basic_publish(
                blocked.prepare_message('fast%d' % i), '', fast_queue)

        blocked.basic_consume(slow_queue, False, callback=lambda *a: None,
                              consumer_tag='tag-slow')
        healthy.basic_consume(fast_queue, False, callback=lambda *a: None,
                              consumer_tag='tag-fast')
        blocked.basic_qos(prefetch_count=1)
        healthy.basic_qos(prefetch_count=1)

        # blocked never acknowledges, so its single prefetch slot stays full
        slow_msg = blocked.basic_get(slow_queue)
        assert slow_msg is not None
        assert blocked._consumers
        assert blocked.qos.can_consume() is False
        with pytest.raises(virtual.Empty):
            blocked.drain_events()

        # the healthy channel's cap is untouched: its slot is still open even
        # though both channels are attached to the same in-memory queues
        assert healthy.qos.can_consume() is True
        fast_msg = healthy.basic_get(fast_queue)
        assert fast_msg.body == b'fast0'
        assert healthy.qos.can_consume() is False
        healthy.basic_ack(fast_msg.delivery_tag)
        assert healthy.qos.can_consume() is True
        assert healthy.basic_get(fast_queue).body == b'fast1'
