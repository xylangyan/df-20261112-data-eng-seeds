"""
Opt-in round-robin draining on the virtual transport (``memory://``).

Queue ``A`` has a sustained backlog, while a single message arrives on queue
``B`` part-way through draining. With the default ``fair`` strategy the
:class:`~kombu.utils.scheduling.FairCycle` keeps skipping an empty queue, but
``B`` still has to wait for the current ``A`` read; with
``queue_order_strategy='round_robin'`` each drain call starts one explicit
round over the active queues, so empty and prefetch-blocked queues are skipped
without stretching the wait.

Fairness here is structural (rounds are counted from the cycle cursor), not
timed: nothing in this example sleeps, so the output can be diffed in CI.

FIFO is only guaranteed *within* each queue, publish and delivery semantics
are untouched.
"""
from __future__ import annotations

import json
from uuid import uuid4

from kombu import Connection

QUEUES = ('A', 'B')
PREFETCH = 2


def drain_record(channel, count):
    """Drain ``count`` times, returning one record per received message."""
    record = []
    for _ in range(count):
        channel.drain_events()
        qos = channel.qos
        message = next(reversed(qos._delivered.values()))
        record.append({
            'round': channel.cycle.pos,
            'queue': message.delivery_info['routing_key'][0],
            'body': message.body.decode(),
            'unacked_before_ack': len(qos._delivered) - len(qos._dirty),
            'prefetch_count': qos.prefetch_count,
        })
        channel.basic_ack(message.delivery_tag)
    return record


def run(strategy):
    connection = Connection(
        'memory://',
        transport_options={'queue_order_strategy': strategy},
    )
    channel = connection.channel()
    # memory transport queues are process-wide state: use unique names
    suffix = uuid4().hex
    queue_names = {name: '%s-%s' % (name, suffix) for name in QUEUES}
    for queue in queue_names.values():
        channel.queue_declare(queue)
        channel.basic_consume(
            queue, False, callback=lambda *args: None,
            consumer_tag='consume-' + queue,
        )
    channel.basic_qos(prefetch_count=PREFETCH)

    # A is saturated before draining starts.
    for i in range(8):
        channel.basic_publish(
            channel.prepare_message('A%d' % i), '', queue_names['A'])

    # B arrives while A is still being drained.
    head = drain_record(channel, 3)
    channel.basic_publish(
        channel.prepare_message('B0'), '', queue_names['B'])
    tail = drain_record(channel, 5)

    record = head + tail
    inserted_after = len(head)
    index_of_b = next(
        index for index, entry in enumerate(record)
        if entry['queue'] == 'B'
    )
    return {
        'strategy': strategy,
        'inserted_after_drains': inserted_after,
        'b_first_seen_at_drain': index_of_b + 1,
        'b_waited_extra_drains': index_of_b - inserted_after,
        'max_unacked_before_ack': max(
            entry['unacked_before_ack'] for entry in record),
        'prefetch_count': PREFETCH,
        'record': record,
    }


if __name__ == '__main__':
    reports = [run('fair'), run('round_robin')]
    print(json.dumps(reports, indent=2, sort_keys=True))
    for report in reports:
        assert report['max_unacked_before_ack'] <= report['prefetch_count']
