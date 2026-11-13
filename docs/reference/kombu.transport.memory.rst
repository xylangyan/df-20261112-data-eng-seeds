==================================================
 In-memory Transport - ``kombu.transport.memory``
==================================================

.. currentmodule:: kombu.transport.memory

.. automodule:: kombu.transport.memory

    .. contents::
        :local:

    Transport Options
    -----------------

    .. describe:: queue_order_strategy

        How a channel chooses the next queue while draining. The default
        ``fair`` keeps the historical behavior. ``round_robin`` drains one
        explicit round per call: empty queues and queues blocked by the
        channel's ``prefetch_count`` are skipped, and a blocked queue rejoins
        the rotation once a message is acknowledged. FIFO is only guaranteed
        within each queue. Intended for in-memory tests and lightweight jobs,
        e.g. ``Connection('memory://', transport_options={
        'queue_order_strategy': 'round_robin'})``. See
        :class:`~kombu.utils.scheduling.QoSFairCycle`.

    Transport
    ---------

    .. autoclass:: Transport
        :members:
        :undoc-members:

    Channel
    -------

    .. autoclass:: Channel
        :members:
        :undoc-members:
