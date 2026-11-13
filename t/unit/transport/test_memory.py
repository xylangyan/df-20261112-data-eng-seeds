from __future__ import annotations

import socket

import pytest

from kombu import Connection, Consumer, Exchange, Producer, Queue


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

    def test_close_channel_restores_unacked_in_delivery_order(self):
        # Two channels on one connection: the first reads four numbered
        # messages and acks only the middle one; after it is closed the
        # second channel must see the remaining messages in their original
        # relative order, each flagged as redelivered, without the acked one.
        with Connection(transport='memory') as conn:
            queue = Queue('memory_restore_order', routing_key='memory_restore_order')

            chan_a = conn.channel()
            queue(chan_a).declare()
            producer = Producer(chan_a)
            for seq in (1, 2, 3, 4):
                producer.publish({'seq': seq}, routing_key='memory_restore_order')

            first_read = []
            for _ in range(4):
                message = queue(chan_a).get()
                first_read.append(message.payload['seq'])
                if message.payload['seq'] == 2:
                    message.ack()
            assert first_read == [1, 2, 3, 4]

            chan_a.close()

            chan_b = conn.channel()
            second_read, redelivered = [], []
            while True:
                message = queue(chan_b).get()
                if message is None:
                    break
                second_read.append(message.payload['seq'])
                redelivered.append(message.delivery_info.get('redelivered'))
                message.ack()

            assert second_read == [1, 3, 4]
            assert redelivered == [True, True, True]

    def test_close_channel_does_not_disturb_sibling_channel(self):
        with Connection(transport='memory') as conn:
            queue = Queue('memory_sibling', routing_key='memory_sibling')

            chan_a = conn.channel()
            queue(chan_a).declare()
            producer = Producer(chan_a)
            producer.publish({'seq': 1}, routing_key='memory_sibling')

            chan_b = conn.channel()
            message = queue(chan_b).get()
            assert message.payload['seq'] == 1
            message.ack()

            # Closing the consumer channel must neither reset the shared
            # queue registry nor drop messages for sibling channels.
            chan_b.close()
            assert 'memory_sibling' in chan_b.__class__.queues

            producer.publish({'seq': 2}, routing_key='memory_sibling')

            chan_c = conn.channel()
            message = queue(chan_c).get()
            assert message.payload['seq'] == 2
            message.ack()

    def test_basic_ack_multiple(self):
        with Connection(transport='memory') as conn:
            queue = Queue('memory_multi_ack', routing_key='memory_multi_ack')

            channel = conn.channel()
            queue(channel).declare()
            producer = Producer(channel)
            for seq in (1, 2, 3, 4):
                producer.publish({'seq': seq}, routing_key='memory_multi_ack')

            messages = [queue(channel).get() for _ in range(4)]
            messages[2].ack(multiple=True)
            channel.qos._flush()
            assert len(channel.qos._delivered) == 1

            channel.close()

            channel2 = conn.channel()
            message = queue(channel2).get()
            assert message.payload['seq'] == 4
            assert message.delivery_info['redelivered'] is True
            assert queue(channel2).get() is None

    def test_late_ack_after_channel_close(self):
        with Connection(transport='memory') as conn:
            queue = Queue('memory_late_ack', routing_key='memory_late_ack')

            channel = conn.channel()
            queue(channel).declare()
            producer = Producer(channel)
            producer.publish({'seq': 1}, routing_key='memory_late_ack')

            message = queue(channel).get()
            channel.close()

            # A late acknowledgement after close is silently dropped rather
            # than raising; the unacked copy was already restored.
            message.ack()
            channel2 = conn.channel()
            redelivered = queue(channel2).get()
            assert redelivered.payload['seq'] == 1
            assert redelivered.delivery_info['redelivered'] is True
            redelivered.ack()

    def test_close_connection_resets_shared_state(self):
        with Connection(transport='memory') as conn:
            queue = Queue('memory_state_reset', routing_key='memory_state_reset')
            channel = conn.channel()
            queue(channel).declare()
            Producer(channel).publish({'seq': 1}, routing_key='memory_state_reset')
            channel.qos.restore_at_shutdown = False
            assert queue(channel).get() is not None

        with Connection(transport='memory') as conn:
            queue = Queue('memory_state_reset', routing_key='memory_state_reset')
            channel = conn.channel()
            queue(channel).declare()
            assert queue(channel).get() is None

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
