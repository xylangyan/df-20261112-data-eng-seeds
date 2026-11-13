"""Virtual AMQ Exchange.

Implementations of the standard exchanges defined by the AMQ protocol.
"""

from __future__ import annotations

import re

from kombu.utils.text import escape_regex


class ExchangeType:
    """Base class for exchanges.

    Implements the specifics for an exchange type.

    Arguments:
    ---------
        channel (ChannelT): AMQ Channel.
    """

    type = None

    def __init__(self, channel):
        self.channel = channel

    def lookup(self, table, exchange, routing_key, default, headers=None):
        """Lookup all queues matching `routing_key` in `exchange`.

        Returns
        -------
            str: queue name, or 'default' if no queues matched.
        """
        raise NotImplementedError('subclass responsibility')

    def prepare_bind(self, queue, exchange, routing_key, arguments):
        """Prepare queue-binding.

        Returns
        -------
            Tuple[str, Pattern, str]: of `(routing_key, regex, queue)`
                to be stored for bindings to this exchange.
        """
        return routing_key, None, queue

    def equivalent(self, prev, exchange, type,
                   durable, auto_delete, arguments):
        """Return true if `prev` and `exchange` is equivalent."""
        return (type == prev['type'] and
                durable == prev['durable'] and
                auto_delete == prev['auto_delete'] and
                (arguments or {}) == (prev['arguments'] or {}))


class DirectExchange(ExchangeType):
    """Direct exchange.

    The `direct` exchange routes based on exact routing keys.
    """

    type = 'direct'

    def lookup(self, table, exchange, routing_key, default, headers=None):
        return {
            queue for rkey, _, queue in table
            if rkey == routing_key
        }

    def deliver(self, message, exchange, routing_key, **kwargs):
        _lookup = self.channel._lookup
        _put = self.channel._put
        for queue in _lookup(exchange, routing_key):
            _put(queue, message, **kwargs)


class TopicExchange(ExchangeType):
    """Topic exchange.

    The `topic` exchange routes messages based on words separated by
    dots, using wildcard characters ``*`` (any single word), and ``#``
    (one or more words).
    """

    type = 'topic'

    #: map of wildcard to regex conversions
    wildcards = {'*': r'[^\.]+',
                 '#': r'.*?'}

    #: compiled regex cache
    _compiled = {}

    def lookup(self, table, exchange, routing_key, default, headers=None):
        return {
            queue for rkey, pattern, queue in table
            if self._match(pattern, routing_key)
        }

    def deliver(self, message, exchange, routing_key, **kwargs):
        _lookup = self.channel._lookup
        _put = self.channel._put
        deadletter = self.channel.deadletter_queue
        for queue in [q for q in _lookup(exchange, routing_key)
                      if q and q != deadletter]:
            _put(queue, message, **kwargs)

    def prepare_bind(self, queue, exchange, routing_key, arguments):
        return routing_key, self.key_to_pattern(routing_key), queue

    def key_to_pattern(self, rkey):
        """Get the corresponding regex for any routing key."""
        return '^%s$' % (r'\.'.join(
            self.wildcards.get(word, word)
            for word in escape_regex(rkey, '.#*').split('.')
        ))

    def _match(self, pattern, string):
        """Match regular expression (cached).

        Same as :func:`re.match`, except the regex is compiled and cached,
        then reused on subsequent matches with the same pattern.
        """
        try:
            compiled = self._compiled[pattern]
        except KeyError:
            compiled = self._compiled[pattern] = re.compile(pattern, re.U)
        return compiled.match(string)


class FanoutExchange(ExchangeType):
    """Fanout exchange.

    The `fanout` exchange implements broadcast messaging by delivering
    copies of all messages to all queues bound to the exchange.

    To support fanout the virtual channel needs to store the table
    as shared state.  This requires that the `Channel.supports_fanout`
    attribute is set to true, and the `Channel._queue_bind` and
    `Channel.get_table` methods are implemented.

    See Also
    --------
        the redis backend for an example implementation of these methods.
    """

    type = 'fanout'

    def lookup(self, table, exchange, routing_key, default, headers=None):
        return {queue for _, _, queue in table}

    def deliver(self, message, exchange, routing_key, **kwargs):
        if self.channel.supports_fanout:
            self.channel._put_fanout(
                exchange, message, routing_key, **kwargs)


class HeadersExchange(ExchangeType):
    """Headers exchange.

    The `headers` exchange routes messages based on their message headers,
    ignoring the routing key.  A queue is bound with an arguments table
    describing the header names and values it expects, plus a special
    ``x-match`` entry that selects how the entries are combined:

    * ``all`` (default): every header named in the binding arguments must be
      present on the message with the exact same type and value.
    * ``any``: at least one of the named headers must be present with the
      exact same type and value.

    Matching is exact on both type and value: a bound value of the string
    ``'1'`` does not match a message header value of the integer ``1``.

    A header that is absent from the message and a header present with an
    explicit empty value (``None``, ``''``, ``[]`` ...) are different
    things: the former is never a match, while the latter matches an equally
    empty bound value of the same type.  ``x-match`` itself is never used as
    a matching criterion.
    """

    type = 'headers'

    #: binding argument selecting the matching algorithm.
    MATCH_HEADER = 'x-match'

    MATCH_ALL = 'all'
    MATCH_ANY = 'any'

    def prepare_bind(self, queue, exchange, routing_key, arguments):
        # The second slot of a binding triple normally holds the routing
        # pattern (as for the topic exchange); for headers exchanges it holds
        # the arguments table used to match message headers.
        return routing_key, dict(arguments or {}), queue

    def lookup(self, table, exchange, routing_key, default, headers=None):
        headers = headers or {}
        return {
            queue
            for _, arguments, queue in table
            if self._match_binding(arguments, headers)
        }

    def deliver(self, message, exchange, routing_key, **kwargs):
        _lookup = self.channel._lookup
        _put = self.channel._put
        for queue in _lookup(
            exchange, routing_key, headers=message.get('headers')
        ):
            _put(queue, message, **kwargs)

    def _match_binding(self, arguments, headers):
        match = (arguments.get(self.MATCH_HEADER)
                 or self.MATCH_ALL).lower()
        criteria = [
            (name, value)
            for name, value in (arguments or {}).items()
            if name != self.MATCH_HEADER
        ]
        if not criteria:
            # Nothing to match on, mirroring RabbitMQ, which does not route
            # messages to bindings without any header criteria.
            return False
        if match == self.MATCH_ANY:
            return any(
                self._match_header(headers, name, value)
                for name, value in criteria
            )
        return all(
            self._match_header(headers, name, value)
            for name, value in criteria
        )

    @staticmethod
    def _match_header(headers, name, value):
        # ``in`` distinguishes a missing header from a header that is
        # explicitly present with an empty/``None`` value.
        if name not in headers:
            return False
        return headers[name] == value and type(headers[name]) is type(value)


#: Map of standard exchange types and corresponding classes.
STANDARD_EXCHANGE_TYPES = {
    'direct': DirectExchange,
    'topic': TopicExchange,
    'fanout': FanoutExchange,
    'headers': HeadersExchange,
}
