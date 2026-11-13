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

    def test_headers_exchange_routes_on_message_headers(self):
        channel = self.c.channel()
        headers_exchange = Exchange('test_transport_memory_headers',
                                    type='headers')

        # all: every header must match exactly (type and value).
        q_all = Queue(
            'test_headers_all', exchange=headers_exchange,
            binding_arguments={
                'x-match': 'all', 'source': 'billing', 'env': 'prod',
            },
        )
        # any: a single matching header is enough.
        q_any = Queue(
            'test_headers_any', exchange=headers_exchange,
            binding_arguments={
                'x-match': 'any', 'source': 'audit', 'env': 'prod',
            },
        )
        # explicit empty value: only a header that is present with None
        # matches; a missing header never does.
        q_empty = Queue(
            'test_headers_empty', exchange=headers_exchange,
            binding_arguments={'x-match': 'all', 'trace_id': None},
        )
        # Second binding on q_any with different arguments: messages
        # matching both must still arrive only once.
        q_any_second_binding = Queue(
            'test_headers_any', exchange=headers_exchange,
            binding_arguments={
                'x-match': 'all', 'source': 'audit', 'env': 'prod',
            },
        )
        for queue in (q_all, q_any, q_empty, q_any_second_binding):
            queue(channel).declare()

        producer = Producer(channel)
        messages = [
            ('m1_billing_prod', {'source': 'billing', 'env': 'prod'}),
            ('m2_audit_prod', {'source': 'audit', 'env': 'prod'}),
            ('m3_billing_dev', {'source': 'billing', 'env': 'dev'}),
            ('m4_explicit_none',
             {'source': 'billing', 'env': 'prod', 'trace_id': None}),
            ('m5_missing_trace', {'source': 'billing', 'env': 'prod'}),
            ('m6_wrong_type',
             {'source': 'billing', 'env': 'prod', 'trace_id': 1}),
        ]
        for label, headers in messages:
            producer.publish(
                label, exchange=headers_exchange, routing_key='',
                headers=headers, serializer=None, content_type='text/plain',
            )

        def received(queue):
            bodies = []
            while True:
                message = queue(channel).get()
                if message is None:
                    break
                bodies.append(message.payload)
            return bodies

        assert received(q_all) == [
            'm1_billing_prod',
            'm4_explicit_none',
            'm5_missing_trace',
            'm6_wrong_type',
        ]
        # m2 matches both bindings of this queue and must appear once.
        assert received(q_any) == [
            'm1_billing_prod',
            'm2_audit_prod',
            'm4_explicit_none',
            'm5_missing_trace',
            'm6_wrong_type',
        ]
        assert received(q_empty) == ['m4_explicit_none']

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
