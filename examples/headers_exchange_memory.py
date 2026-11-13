"""Route messages by headers on the in-memory transport.

Declares a ``headers`` exchange and three queues, then publishes messages
that differ only in their headers and prints which queue each message
actually arrived in.

Binding rules demonstrated:

* ``x-match: all`` -- every header in the binding must be present on the
  message with the exact same type and value.
* ``x-match: any`` -- at least one of the bound headers must match.
* A header missing from the message never matches, while a header
  explicitly present with an empty value (e.g. ``None``) matches an
  equally empty bound value of the same type.
* A message matching several bindings of the same queue is delivered
  to that queue only once.

Run with:  python examples/headers_exchange_memory.py
"""
from __future__ import annotations

from kombu import Connection, Exchange, Queue

connection = Connection('memory://')
channel = connection.channel()

events = Exchange('events', type='headers', durable=False)

queues = {
    # every header must match
    'q_all': Queue('q_all', exchange=events, binding_arguments={
        'x-match': 'all', 'source': 'billing', 'env': 'prod'}),
    # any single header may match; a second binding on the same queue
    # exercises the deliver-once-per-queue rule
    'q_any': Queue('q_any', exchange=events, binding_arguments={
        'x-match': 'any', 'env': 'prod', 'source': 'audit'}),
    # explicit empty value: only matches a present ``trace_id=None``
    'q_empty': Queue('q_empty', exchange=events, binding_arguments={
        'x-match': 'all', 'trace_id': None}),
}
second_binding_on_q_any = Queue('q_any', exchange=events, binding_arguments={
    'x-match': 'all', 'source': 'audit', 'env': 'prod'})

for queue in [*queues.values(), second_binding_on_q_any]:
    queue(channel).declare()

producer = connection.Producer()

messages = [
    ('m1 billing+prod', {'source': 'billing', 'env': 'prod'}),
    ('m2 audit+prod', {'source': 'audit', 'env': 'prod'}),
    ('m3 billing+dev', {'source': 'billing', 'env': 'dev'}),
    ('m4 trace=None', {'source': 'billing', 'env': 'prod', 'trace_id': None}),
    ('m5 trace missing', {'source': 'billing', 'env': 'prod'}),
    ('m6 trace=1 (int)', {'source': 'billing', 'env': 'prod', 'trace_id': 1}),
]

for label, headers in messages:
    producer.publish(label, exchange=events, routing_key='',
                     headers=headers, serializer=None,
                     content_type='text/plain')

for name, queue in queues.items():
    arrived = []
    while (message := queue(channel).get()) is not None:
        arrived.append(message.payload)
    print(f'{name}: {arrived}')
