Row-wise loading of collections
===============================

`Schema.load <marshmallow.Schema.load>` with ``many=True`` raises a
:exc:`ValidationError <marshmallow.exceptions.ValidationError>` as soon as a
batch contains a bad row. The caller then has to split
`ValidationError.messages <marshmallow.exceptions.ValidationError.messages>`
(an index-keyed mapping) and
`ValidationError.valid_data <marshmallow.exceptions.ValidationError.valid_data>`
apart by hand to decide which rows to review and which to keep.

`Schema.load_many <marshmallow.Schema.load_many>` instead loads each row
independently and returns a `LoadResult
<marshmallow.load_result.LoadResult>` with one `RowResult
<marshmallow.load_result.RowResult>` per input row. It never raises for
invalid rows, so bad rows can be sent to review while the good rows keep
flowing downstream.

.. code-block:: python

    from marshmallow import Schema, fields


    class SensorSchema(Schema):
        id = fields.Integer()
        unit = fields.String()


    class ReadingSchema(Schema):
        sensor = fields.Nested(SensorSchema)
        readings = fields.List(fields.Integer())


    rows = [
        {"sensor": {"id": "1", "unit": "C"}, "readings": [1, 2]},
        {"sensor": {"id": "2", "unit": 42}, "readings": [3, 4]},
        {"sensor": {"id": 3, "unit": "F"}, "readings": [5, "bad", 7]},
        {"sensor": {"id": "4", "unit": "K"}, "readings": [8]},
    ]

    result = ReadingSchema().load_many(rows)

Each `RowResult <marshmallow.load_result.RowResult>` keeps:

- ``index``: the row's position in the original collection.
- ``original``: the input row, before any processing.
- ``data``: the deserialized value. Valid rows hold the fully
  post-processed value; invalid rows hold the partially valid data,
  mirroring
  `ValidationError.valid_data <marshmallow.exceptions.ValidationError.valid_data>`.
- ``errors``: the row's error messages, including nested errors. It is
  ``{}`` when the row is valid.

Nested errors keep their structure, so a bad field and a bad list element
are located by row and by item:

.. code-block:: python

    result.rows[1].errors
    # => {'sensor': {'unit': ['Not a valid string.']}}

    result.rows[2].errors
    # => {'readings': {1: ['Not a valid integer.']}}

The valid rows are available in input order through
`LoadResult.valid_data <marshmallow.load_result.LoadResult.valid_data>`,
and every error is reachable by row index through
`LoadResult.errors <marshmallow.load_result.LoadResult.errors>`.

.. code-block:: python

    result.valid_data
    # => [
    #     {'sensor': {'id': 1, 'unit': 'C'}, 'readings': [1, 2]},
    #     {'sensor': {'id': 4, 'unit': 'K'}, 'readings': [8]},
    # ]

    result.errors
    # => {
    #     1: {'sensor': {'unit': ['Not a valid string.']}},
    #     2: {'readings': {1: ['Not a valid integer.']}},
    # }

Batch vs. row scope
-------------------

Hooks and schema validators split into two scopes:

- Row scope (the default): ``@pre_load``, ``@post_load``, ``@validates``,
  and ``@validates_schema(pass_collection=False)`` run once **per row** and
  see a single row. Their errors are attributed to that row and stored on
  the row's `RowResult.errors <marshmallow.load_result.RowResult.errors>`.
- Batch scope: hooks and ``@validates_schema`` declared with
  ``pass_collection=True`` run **once for the whole collection** and see the
  collection. Their errors cannot be attributed to a single row and are
  stored on `LoadResult.batch_errors
  <marshmallow.load_result.LoadResult.batch_errors>`, also under the
  `BATCH <marshmallow.load_result.BATCH>` (``"_batch"``) key of
  `LoadResult.errors <marshmallow.load_result.LoadResult.errors>`.

The call counts and the data each hook sees are therefore predictable:

- Row-scope ``pre_load`` runs once per input row, including invalid rows.
- Row-scope ``post_load`` and ``@validates_schema`` run once per row that
  has no field errors; by default a row with field errors skips its
  schema-level validators (``skip_on_field_errors=True``).
- Batch-scope ``pre_load`` runs once on the input collection. If it raises,
  no rows are loaded and the error is a batch error.
- Batch-scope schema validators run once, after all rows, on the valid rows.
- Batch-scope ``post_load`` runs once on the valid rows.

An input that is not a sequence of mappings cannot be split into rows and
also produces a batch error rather than row errors.

`Schema.load <marshmallow.Schema.load>` with ``many=True`` is unchanged and
still raises; `Schema.load_many <marshmallow.Schema.load_many>` is the
non-raising alternative.
