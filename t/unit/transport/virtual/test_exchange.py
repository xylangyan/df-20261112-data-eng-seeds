from __future__ import annotations

from unittest.mock import Mock

import pytest

from kombu import Connection
from kombu.transport.virtual import exchange
from t.mocks import Transport


class ExchangeCase:
    type = None

    def setup_method(self):
        if self.type:
            self.e = self.type(Connection(transport=Transport).channel())


class test_Direct(ExchangeCase):
    type = exchange.DirectExchange
    table = [('rFoo', None, 'qFoo'),
             ('rFoo', None, 'qFox'),
             ('rBar', None, 'qBar'),
             ('rBaz', None, 'qBaz')]

    @pytest.mark.parametrize('exchange,routing_key,default,expected', [
        ('eFoo', 'rFoo', None, {'qFoo', 'qFox'}),
        ('eMoz', 'rMoz', 'DEFAULT', set()),
        ('eBar', 'rBar', None, {'qBar'}),
    ])
    def test_lookup(self, exchange, routing_key, default, expected):
        assert self.e.lookup(
            self.table, exchange, routing_key, default) == expected


class test_Fanout(ExchangeCase):
    type = exchange.FanoutExchange
    table = [(None, None, 'qFoo'),
             (None, None, 'qFox'),
             (None, None, 'qBar')]

    def test_lookup(self):
        assert self.e.lookup(self.table, 'eFoo', 'rFoo', None) == {
            'qFoo', 'qFox', 'qBar',
        }

    def test_deliver_when_fanout_supported(self):
        self.e.channel = Mock()
        self.e.channel.supports_fanout = True
        message = Mock()

        self.e.deliver(message, 'exchange', 'rkey')
        self.e.channel._put_fanout.assert_called_with(
            'exchange', message, 'rkey',
        )

    def test_deliver_when_fanout_unsupported(self):
        self.e.channel = Mock()
        self.e.channel.supports_fanout = False

        self.e.deliver(Mock(), 'exchange', None)
        self.e.channel._put_fanout.assert_not_called()


class test_Topic(ExchangeCase):
    type = exchange.TopicExchange
    table = [
        ('stock.#', None, 'rFoo'),
        ('stock.us.*', None, 'rBar'),
    ]

    def setup_method(self):
        super().setup_method()
        self.table = [(rkey, self.e.key_to_pattern(rkey), queue)
                      for rkey, _, queue in self.table]

    def test_prepare_bind(self):
        x = self.e.prepare_bind('qFoo', 'eFoo', 'stock.#', {})
        assert x == ('stock.#', r'^stock\..*?$', 'qFoo')

    @pytest.mark.parametrize('exchange,routing_key,default,expected', [
        ('eFoo', 'stock.us.nasdaq', None, {'rFoo', 'rBar'}),
        ('eFoo', 'stock.europe.OSE', None, {'rFoo'}),
        ('eFoo', 'stockxeuropexOSE', None, set()),
        ('eFoo', 'candy.schleckpulver.snap_crackle', None, set()),
        # '*' is a single word: only 'stock.#' may match a longer key.
        ('eFoo', 'stock.us.nasdaq.tech', None, {'rFoo'}),
    ])
    def test_lookup(self, exchange, routing_key, default, expected):
        assert self.e.lookup(
            self.table, exchange, routing_key, default) == expected
        assert self.e._compiled

    def test_deliver(self):
        self.e.channel = Mock()
        self.e.channel._lookup.return_value = ('a', 'b')
        message = Mock()
        self.e.deliver(message, 'exchange', 'rkey')

        assert self.e.channel._put.call_args_list == [
            (('a', message), {}),
            (('b', message), {}),
        ]


class test_Headers(ExchangeCase):
    type = exchange.HeadersExchange

    def prepare(self, queue, arguments):
        return self.e.prepare_bind(queue, 'eFoo', '', arguments)

    def test_prepare_bind(self):
        args = {'x-match': 'any', 'source': 'billing'}
        assert self.e.prepare_bind('qFoo', 'eFoo', '', args) == (
            '', args, 'qFoo',
        )

    def test_lookup_all(self):
        table = [
            self.prepare('qAll', {
                'x-match': 'all', 'source': 'billing', 'env': 'prod',
            }),
        ]
        headers = {'source': 'billing', 'env': 'prod'}
        assert self.e.lookup(table, 'eFoo', '', None, headers) == {'qAll'}
        assert self.e.lookup(
            table, 'eFoo', '', None, {'source': 'billing'}) == set()

    def test_lookup_any(self):
        table = [
            self.prepare('qAny', {
                'x-match': 'any', 'source': 'billing', 'env': 'prod',
            }),
        ]
        assert self.e.lookup(
            table, 'eFoo', '', None, {'source': 'billing'}) == {'qAny'}
        assert self.e.lookup(
            table, 'eFoo', '', None, {'env': 'prod'}) == {'qAny'}
        assert self.e.lookup(
            table, 'eFoo', '', None, {'source': 'audit'}) == set()

    @pytest.mark.parametrize('match', ['all', 'ALL', 'Any', 'ANY'])
    def test_x_match_is_case_insensitive(self, match):
        table = [self.prepare('qFoo', {'x-match': match, 'a': 1})]
        assert self.e.lookup(table, 'eFoo', '', None, {'a': 1}) == {'qFoo'}

    def test_default_x_match_is_all(self):
        table = [self.prepare('qFoo', {'a': 1, 'b': 2})]
        assert self.e.lookup(
            table, 'eFoo', '', None, {'a': 1}) == set()
        assert self.e.lookup(
            table, 'eFoo', '', None, {'a': 1, 'b': 2}) == {'qFoo'}

    def test_missing_header_does_not_match_explicit_empty_value(self):
        none_table = [self.prepare('qNone', {'trace_id': None})]
        empty_table = [self.prepare('qEmpty', {'trace_id': ''})]

        # absent from the message: never a match, even for empty bindings
        assert self.e.lookup(none_table, 'eFoo', '', None, {}) == set()
        assert self.e.lookup(empty_table, 'eFoo', '', None, {}) == set()
        # explicitly present empty values match an equal empty value
        assert self.e.lookup(
            none_table, 'eFoo', '', None, {'trace_id': None}) == {'qNone'}
        assert self.e.lookup(
            empty_table, 'eFoo', '', None, {'trace_id': ''}) == {'qEmpty'}
        # and do not cross-match one another
        assert self.e.lookup(
            none_table, 'eFoo', '', None, {'trace_id': ''}) == set()
        assert self.e.lookup(
            empty_table, 'eFoo', '', None, {'trace_id': None}) == set()

    @pytest.mark.parametrize('value,expected', [
        (1, True),
        (True, False),
        (1.0, False),
        ('1', False),
    ])
    def test_match_is_exact_on_type_and_value(self, value, expected):
        table = [self.prepare('qFoo', {'retry': 1})]
        matched = self.e.lookup(
            table, 'eFoo', '', None, {'retry': value}) == {'qFoo'}
        assert matched is expected

    def test_no_criteria_never_matches(self):
        table = [self.prepare('qFoo', {'x-match': 'all'})]
        assert self.e.lookup(table, 'eFoo', '', None, {}) == set()
        assert self.e.lookup(
            table, 'eFoo', '', None, {'a': 1}) == set()

    def test_overlapping_bindings_deliver_once_per_queue(self):
        # Two separate bindings on the same queue both match this message.
        table = [
            self.prepare('qFoo', {'x-match': 'all', 'a': 1}),
            self.prepare('qFoo', {'x-match': 'all', 'a': 1, 'b': 2}),
            self.prepare('qBar', {'x-match': 'all', 'a': 1}),
        ]
        assert self.e.lookup(
            table, 'eFoo', '', None, {'a': 1, 'b': 2}) == {'qFoo', 'qBar'}

    def test_deliver_passes_message_headers(self):
        self.e.channel = Mock()
        self.e.channel._lookup.return_value = ('a', 'b')
        message = {'headers': {'source': 'billing'}}

        self.e.deliver(message, 'exchange', '')

        self.e.channel._lookup.assert_called_once_with(
            'exchange', '', headers={'source': 'billing'})
        assert self.e.channel._put.call_args_list == [
            (('a', message), {}),
            (('b', message), {}),
        ]


class test_TopicMultibind(ExchangeCase):
    # Testing message delivery in case of multiple overlapping
    # bindings for the same queue. As AMQP states, in case of
    # overlapping bindings, a message must be delivered once to
    # each matching queue.
    type = exchange.TopicExchange
    table = [
        ('stock', None, 'rFoo'),
        ('stock.#', None, 'rFoo'),
        ('stock.us.*', None, 'rFoo'),
        ('#', None, 'rFoo'),
    ]

    def setup_method(self):
        super().setup_method()
        self.table = [(rkey, self.e.key_to_pattern(rkey), queue)
                      for rkey, _, queue in self.table]

    @pytest.mark.parametrize('exchange,routing_key,default,expected', [
        ('eFoo', 'stock.us.nasdaq', None, {'rFoo'}),
        ('eFoo', 'stock.europe.OSE', None, {'rFoo'}),
        ('eFoo', 'stockxeuropexOSE', None, {'rFoo'}),
        ('eFoo', 'candy.schleckpulver.snap_crackle', None, {'rFoo'}),
    ])
    def test_lookup(self, exchange, routing_key, default, expected):
        assert self.e._compiled
        assert self.e.lookup(
            self.table, exchange, routing_key, default) == expected


class test_ExchangeType(ExchangeCase):
    type = exchange.ExchangeType

    def test_lookup(self):
        with pytest.raises(NotImplementedError):
            self.e.lookup([], 'eFoo', 'rFoo', None)

    def test_prepare_bind(self):
        assert self.e.prepare_bind('qFoo', 'eFoo', 'rFoo', {}) == (
            'rFoo', None, 'qFoo',
        )

    e1 = {
        'type': 'direct',
        'durable': True,
        'auto_delete': True,
        'arguments': {},
    }
    e2 = dict(e1, arguments={'expires': 3000})

    @pytest.mark.parametrize('ex,eq,name,type,durable,auto_delete,arguments', [
        (e1, True, 'eFoo', 'direct', True, True, {}),
        (e1, False, 'eFoo', 'topic', True, True, {}),
        (e1, False, 'eFoo', 'direct', False, True, {}),
        (e1, False, 'eFoo', 'direct', True, False, {}),
        (e1, False, 'eFoo', 'direct', True, True, {'expires': 3000}),
        (e2, True, 'eFoo', 'direct', True, True, {'expires': 3000}),
        (e2, False, 'eFoo', 'direct', True, True, {'expires': 6000}),
    ])
    def test_equivalent(
            self, ex, eq, name, type, durable, auto_delete, arguments):
        is_eq = self.e.equivalent(
            ex, name, type, durable, auto_delete, arguments)
        assert is_eq if eq else not is_eq
