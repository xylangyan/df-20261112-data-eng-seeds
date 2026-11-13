"""Tests for `Schema.load_many`, the row-wise collection loader."""

import pytest

from marshmallow import (
    BATCH,
    EXCLUDE,
    INCLUDE,
    LoadResult,
    RowResult,
    Schema,
    ValidationError,
    fields,
    post_load,
    pre_load,
    validates,
    validates_schema,
)


class SensorSchema(Schema):
    id = fields.Integer()
    unit = fields.String()


class ReadingSchema(Schema):
    sensor = fields.Nested(SensorSchema)
    readings = fields.List(fields.Integer())


# Four rows containing two kinds of nested errors:
# row 1 has an invalid item inside a Nested object,
# row 2 has an invalid item inside a List field.
ROWS = [
    {"sensor": {"id": "1", "unit": "C"}, "readings": [1, 2]},
    {"sensor": {"id": "2", "unit": 42}, "readings": [3, 4]},
    {"sensor": {"id": 3, "unit": "F"}, "readings": [5, "bad", 7]},
    {"sensor": {"id": "4", "unit": "K"}, "readings": [8]},
]


def test_load_many_returns_row_results_for_every_input_row():
    result = ReadingSchema().load_many(ROWS)

    assert isinstance(result, LoadResult)
    assert len(result) == 4
    assert all(isinstance(row, RowResult) for row in result.rows)
    assert [row.index for row in result.rows] == [0, 1, 2, 3]
    assert [row.original for row in result.rows] == ROWS


def test_load_many_locates_nested_errors_by_row_and_item():
    result = ReadingSchema().load_many(ROWS)

    # Row 1: nested object error -> row 1, field "sensor", item "unit".
    assert result.rows[1].errors == {
        "sensor": {"unit": ["Not a valid string."]}
    }
    # Row 2: list element error -> row 2, field "readings", item 1.
    assert result.rows[2].errors == {
        "readings": {1: ["Not a valid integer."]}
    }
    # The same shape is reachable through the index-keyed error mapping.
    assert result.errors == {
        1: {"sensor": {"unit": ["Not a valid string."]}},
        2: {"readings": {1: ["Not a valid integer."]}},
    }
    assert result.rows[0].valid
    assert result.rows[3].valid


def test_load_many_returns_valid_rows_in_input_order():
    result = ReadingSchema().load_many(ROWS)

    assert [row.index for row in result.valid_rows] == [0, 3]
    assert result.valid_data == [
        {"sensor": {"id": 1, "unit": "C"}, "readings": [1, 2]},
        {"sensor": {"id": 4, "unit": "K"}, "readings": [8]},
    ]


def test_load_many_keeps_partial_data_on_invalid_rows():
    result = ReadingSchema().load_many(ROWS)

    # The bad Nested value is dropped, but the valid parts of the row remain.
    assert result.rows[1].data == {
        "sensor": {"id": 2},
        "readings": [3, 4],
    }
    # The bad list element is skipped, the valid elements are kept.
    assert result.rows[2].data == {
        "sensor": {"id": 3, "unit": "F"},
        "readings": [5, 7],
    }


def test_load_many_accepts_tuples_and_empty_collections():
    result = ReadingSchema().load_many(tuple(ROWS))
    assert [row.index for row in result.rows] == [0, 1, 2, 3]

    empty = ReadingSchema().load_many([])
    assert empty.rows == []
    assert empty.valid_data == []
    assert empty.errors == {}
    assert empty.batch_errors == {}


@pytest.mark.parametrize("bad_input", [None, 1, 1.5, object(), {"value": 1}, "rows"])
def test_load_many_reports_non_sequence_input_as_batch_error(bad_input):
    result = ReadingSchema().load_many(bad_input)

    assert result.rows == []
    assert result.batch_errors == {"_schema": ["Invalid input type."]}
    assert result.errors == {BATCH: {"_schema": ["Invalid input type."]}}


def test_load_many_partial_and_unknown_are_passed_to_each_row():
    class PartialSchema(Schema):
        required = fields.Integer(required=True)
        optional = fields.Integer()

    schema = PartialSchema()
    result = schema.load_many(
        [{"optional": "1"}, {"optional": "2", "extra": 3}],
        partial=True,
        unknown=INCLUDE,
    )
    assert result.valid_data == [
        {"optional": 1},
        {"optional": 2, "extra": 3},
    ]


def test_load_many_unknown_raise_marks_only_the_offending_row():
    class StrictSchema(Schema):
        value = fields.Integer()

    result = StrictSchema().load_many(
        [{"value": 1}, {"value": 2, "extra": 3}], unknown=EXCLUDE
    )
    assert result.valid_data == [{"value": 1}, {"value": 2}]

    result = StrictSchema().load_many([{"value": 1}, {"value": 2, "extra": 3}])
    assert result.rows[0].valid
    assert result.rows[1].errors == {"extra": ["Unknown field."]}
    assert result.valid_data == [{"value": 1}]


def test_load_many_invokes_row_processors_once_per_row():
    seen = {"pre": [], "post": []}

    class HookedSchema(Schema):
        sensor = fields.Nested(SensorSchema)
        readings = fields.List(fields.Integer())

        @pre_load
        def preprocess(self, item, many, **kwargs):
            seen["pre"].append(dict(item))
            return item

        @post_load
        def postprocess(self, item, many, **kwargs):
            seen["post"].append(dict(item))
            return item

    result = HookedSchema().load_many(ROWS)

    # pre_load runs once per input row, always seeing a single row.
    assert seen["pre"] == ROWS
    # post_load runs once per valid row, seeing the deserialized row.
    assert seen["post"] == [
        {"sensor": {"id": 1, "unit": "C"}, "readings": [1, 2]},
        {"sensor": {"id": 4, "unit": "K"}, "readings": [8]},
    ]
    assert result.valid_data == seen["post"]


def test_load_many_invokes_collection_processors_once_for_the_batch():
    seen = {"pre": [], "post": []}

    class HookedSchema(Schema):
        value = fields.Integer()

        @pre_load(pass_collection=True)
        def preprocess(self, items, many, **kwargs):
            seen["pre"].append(items)
            return items

        @post_load(pass_collection=True)
        def postprocess(self, items, many, **kwargs):
            seen["post"].append(items)
            return items

    result = HookedSchema().load_many(
        [{"value": 1}, {"value": "bad"}, {"value": 3}]
    )

    # Collection-level hooks run exactly once, on the whole batch.
    assert seen["pre"] == [[{"value": 1}, {"value": "bad"}, {"value": 3}]]
    # The collection-level post_load sees only the valid rows.
    assert seen["post"] == [[{"value": 1}, {"value": 3}]]
    assert result.valid_data == [{"value": 1}, {"value": 3}]


def test_load_many_collection_pre_load_error_is_a_batch_error():
    class RejectingSchema(Schema):
        value = fields.Integer()

        @pre_load(pass_collection=True)
        def reject(self, items, many, **kwargs):
            raise ValidationError("batch rejected")

    result = RejectingSchema().load_many([{"value": 1}, {"value": 2}])

    assert result.rows == []
    assert result.batch_errors == {"_schema": ["batch rejected"]}
    assert result.errors == {BATCH: {"_schema": ["batch rejected"]}}
    assert result.valid_data == []


def test_load_many_collection_post_load_error_is_a_batch_error():
    class RejectingSchema(Schema):
        value = fields.Integer()

        @post_load(pass_collection=True)
        def reject(self, items, many, **kwargs):
            raise ValidationError("post-processing failed")

    result = RejectingSchema().load_many([{"value": 1}, {"value": 2}])

    # Rows loaded fine, but the batch-level post-processing failed.
    assert [row.valid for row in result.rows] == [True, True]
    assert result.batch_errors == {"_schema": ["post-processing failed"]}
    assert result.errors == {BATCH: {"_schema": ["post-processing failed"]}}


def test_load_many_row_post_load_error_is_a_row_error():
    class RejectingSchema(Schema):
        value = fields.Integer()

        @post_load
        def reject_odd(self, item, many, **kwargs):
            if item["value"] % 2:
                raise ValidationError({"value": ["odd values are rejected"]})
            return item

    result = RejectingSchema().load_many([{"value": 1}, {"value": 2}])

    assert result.rows[0].errors == {"value": ["odd values are rejected"]}
    assert result.rows[1].valid
    assert result.valid_data == [{"value": 2}]
    assert result.batch_errors == {}


def test_load_many_row_validators_run_per_row():
    calls = []

    class ValidatedSchema(Schema):
        value = fields.Integer()

        @validates("value")
        def validate_value(self, value, **kwargs):
            calls.append(("field", value))
            if value > 2:
                raise ValidationError("too large")

        @validates_schema
        def validate_row(self, data, many, **kwargs):
            calls.append(("row", dict(data)))

    result = ValidatedSchema().load_many([{"value": 1}, {"value": 3}])

    # Field validators run before per-row schema validators. The schema
    # validator of the invalid row is skipped (skip_on_field_errors=True).
    assert calls == [
        ("field", 1),
        ("row", {"value": 1}),
        ("field", 3),
    ]
    assert result.rows[1].errors == {"value": ["too large"]}
    assert result.valid_data == [{"value": 1}]


def test_load_many_collection_validator_runs_once_for_the_batch():
    calls = []

    class ValidatedSchema(Schema):
        value = fields.Integer()

        @validates_schema(pass_collection=True)
        def validate_batch(self, data, many, **kwargs):
            calls.append(list(data))
            if sum(item["value"] for item in data) > 10:
                raise ValidationError("batch too large")

    result = ValidatedSchema().load_many([{"value": 1}, {"value": 2}])

    assert calls == [[{"value": 1}, {"value": 2}]]
    assert result.batch_errors == {}


def test_load_many_collection_validator_error_is_a_batch_error():
    class ValidatedSchema(Schema):
        value = fields.Integer()

        @validates_schema(pass_collection=True)
        def validate_batch(self, data, many, **kwargs):
            if len(data) > 1:
                raise ValidationError("only one row allowed")

    result = ValidatedSchema().load_many([{"value": 1}, {"value": 2}])

    assert [row.valid for row in result.rows] == [True, True]
    assert result.batch_errors == {"_schema": ["only one row allowed"]}
    assert result.errors == {BATCH: {"_schema": ["only one row allowed"]}}


def test_load_many_collection_validator_skipped_on_invalid_rows_by_default():
    calls = []

    class ValidatedSchema(Schema):
        value = fields.Integer()

        @validates_schema(pass_collection=True)
        def validate_batch(self, data, many, **kwargs):
            calls.append(list(data))

    result = ValidatedSchema().load_many([{"value": 1}, {"value": "bad"}])

    assert calls == []
    assert result.batch_errors == {}
    assert result.rows[1].errors == {"value": ["Not a valid integer."]}


def test_load_many_respects_skip_on_field_errors_false():
    calls = []

    class ValidatedSchema(Schema):
        value = fields.Integer()

        @validates_schema(pass_collection=True, skip_on_field_errors=False)
        def validate_batch(self, data, many, **kwargs):
            calls.append(list(data))

    result = ValidatedSchema().load_many([{"value": 1}, {"value": "bad"}])

    # The batch validator still runs once, seeing only the valid rows.
    assert calls == [[{"value": 1}]]
    assert result.rows[1].errors == {"value": ["Not a valid integer."]}


def test_load_many_still_calls_handle_error_per_invalid_row():
    handled = []

    class HandledSchema(Schema):
        value = fields.Integer()

        def handle_error(self, exc, data, **kwargs):
            handled.append((data, exc.messages))

    HandledSchema().load_many([{"value": 1}, {"value": "bad"}])

    assert handled == [({"value": "bad"}, {"value": ["Not a valid integer."]})]


def test_load_many_does_not_change_failing_load_many_true_behavior():
    schema = ReadingSchema()

    with pytest.raises(ValidationError) as excinfo:
        schema.load(ROWS, many=True)

    result = schema.load_many(ROWS)
    # Existing callers still receive exactly the same error mapping.
    assert excinfo.value.messages == result.errors
    # And the legacy valid_data remains the partially valid collection.
    assert excinfo.value.valid_data == [row.data for row in result.rows]


def test_load_result_sequence_protocol():
    result = ReadingSchema().load_many(ROWS)

    assert len(result) == 4
    assert result[0] is result.rows[0]
    assert [row.index for row in result] == [0, 1, 2, 3]
    assert "valid=2" in repr(result)
    assert "invalid=2" in repr(result)


def test_load_result_defaults_are_empty():
    result = LoadResult()

    assert result.rows == []
    assert result.batch_errors == {}
    assert result.valid_rows == []
    assert result.invalid_rows == []
    assert result.valid_data == []
    assert result.errors == {}


def test_row_result_valid_flag():
    valid = RowResult(index=0, original={}, data={"a": 1}, errors={})
    invalid = RowResult(index=1, original={}, data=None, errors={"a": ["bad"]})

    assert valid.valid
    assert not invalid.valid


def test_batch_key_is_exported():
    assert BATCH == "_batch"


def test_load_many_collection_processors_pass_only_valid_originals_when_requested():
    seen = {}

    class HookedSchema(Schema):
        value = fields.Integer()

        @validates_schema(
            pass_collection=True,
            pass_original=True,
            skip_on_field_errors=False,
        )
        def validate_batch(self, data, original, many, **kwargs):
            seen["validator"] = (data, original)

        @post_load(pass_collection=True, pass_original=True)
        def postprocess(self, data, original, many, **kwargs):
            seen["post_load"] = (data, original)
            return data

    HookedSchema().load_many([{"value": 1}, {"value": "bad"}, {"value": 3}])

    valid_data, valid_originals = seen["validator"]
    assert valid_data == [{"value": 1}, {"value": 3}]
    assert valid_originals == [{"value": 1}, {"value": 3}]
    assert seen["post_load"] == (valid_data, valid_originals)


@pytest.mark.parametrize("row", [None, 1, "not a mapping", [1, 2]])
def test_load_many_non_mapping_rows_get_row_level_type_errors(row):
    result = ReadingSchema().load_many([row])

    assert result.rows[0].errors == {"_schema": ["Invalid input type."]}
    assert result.rows[0].data == {}
    assert result.valid_data == []
