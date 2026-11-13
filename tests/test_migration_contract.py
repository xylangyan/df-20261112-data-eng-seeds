"""Frozen migration contract samples for the JSON -> new-warehouse move.

Each sample pins the *current* marshmallow 4.4.0 behavior of a concrete field
contract. Expected values are written as independent literals (or constructed
with the standard library only); they are never derived from
``dump(load(x))``. A sample records, in one row:

* the external JSON-style input,
* the internal object produced by ``Schema.load`` (or ``missing`` data),
* the external representation produced by ``Schema.dump`` of that object,
* the ``ValidationError.messages`` and ``valid_data`` when loading fails.

Run ``pytest tests/test_migration_contract.py -q`` to verify the boundary, or
``python -m tests.test_migration_contract`` to print the Markdown sample table.
"""

import datetime as dt
import decimal
from dataclasses import dataclass
from typing import Any

import pytest

from marshmallow import EXCLUDE, INCLUDE, Schema, ValidationError, fields
from marshmallow import missing as missing_sentinel

INDIA = dt.timezone(dt.timedelta(hours=5, minutes=30))
US_CENTRAL = dt.timezone(dt.timedelta(hours=-6))
UTC = dt.UTC


class DecimalContractSchema(Schema):
    amount = fields.Decimal()
    string_amount = fields.Decimal(as_string=True)
    rounded = fields.Decimal(places=2)
    half_up = fields.Decimal(places=2, rounding=decimal.ROUND_HALF_UP)
    nullable = fields.Decimal(allow_none=True)


class PresenceContractSchema(Schema):
    amount = fields.Decimal()
    note = fields.String()
    defaulted = fields.Decimal(load_default=decimal.Decimal("0.00"))
    dump_fallback = fields.String(dump_default="N/A")
    dump_null = fields.String(dump_default=None)


class DateTimeContractSchema(Schema):
    iso = fields.DateTime()
    rfc = fields.DateTime(format="rfc")
    epoch = fields.DateTime(format="timestamp")
    epoch_ms = fields.DateTime(format="timestamp_ms")
    naive = fields.NaiveDateTime()
    aware = fields.AwareDateTime()
    utc_naive = fields.NaiveDateTime(timezone=UTC)
    default_aware = fields.AwareDateTime(default_timezone=INDIA)


class LineItemSchema(Schema):
    child_id = fields.Integer(data_key="childId")
    price = fields.Decimal(as_string=True, data_key="price")
    when = fields.DateTime(allow_none=True, data_key="when")


class NestedContractSchema(Schema):
    order_id = fields.Integer(required=True, data_key="orderId")
    secret = fields.String(load_only=True, data_key="secret")
    computed = fields.String(dump_only=True, data_key="computed")
    line_items = fields.List(fields.Nested(LineItemSchema), data_key="lineItems")
    amounts = fields.List(fields.Decimal(allow_none=True))
    times = fields.List(fields.DateTime())
    tags = fields.List(fields.String())


@dataclass(frozen=True)
class ContractSample:
    id: str
    schema: Schema
    payload: Any
    expected_load: Any
    expected_dump: Any
    expected_errors: Any = None
    expected_valid_data: Any = None
    dump_payload: Any = missing_sentinel
    note: str = ""

    @property
    def should_fail(self) -> bool:
        return self.expected_errors is not None


SAMPLES: list[ContractSample] = []


def sample(
    sample_id: str,
    schema: Schema,
    payload: Any,
    expected_load: Any,
    expected_dump: Any,
    *,
    expected_errors: Any = None,
    expected_valid_data: Any = None,
    dump_payload: Any = missing_sentinel,
    note: str = "",
) -> None:
    SAMPLES.append(
        ContractSample(
            id=sample_id,
            schema=schema,
            payload=payload,
            expected_load=expected_load,
            expected_dump=expected_dump,
            expected_errors=expected_errors,
            expected_valid_data=expected_valid_data,
            dump_payload=dump_payload,
            note=note,
        )
    )


# ---------------------------------------------------------------------------
# Decimal: values that must round-trip verbatim vs. explicitly normalized ones
# ---------------------------------------------------------------------------

decimal_schema = DecimalContractSchema()

sample(
    "decimal-preserves-string-precision",
    decimal_schema,
    {
        "amount": "123.4500",
        "string_amount": "123.4500",
        "rounded": "123.4500",
        "half_up": "123.4500",
        "nullable": "123.4500",
    },
    # Literal Decimal expectations; scale (trailing zeros) is part of the value.
    {
        "amount": decimal.Decimal("123.4500"),
        "string_amount": decimal.Decimal("123.4500"),
        "rounded": decimal.Decimal("123.45"),
        "half_up": decimal.Decimal("123.45"),
        "nullable": decimal.Decimal("123.4500"),
    },
    # Default dump keeps Decimal objects; as_string=True is the JSON-safe one.
    {
        "amount": decimal.Decimal("123.4500"),
        "string_amount": "123.4500",
        "rounded": decimal.Decimal("123.45"),
        "half_up": decimal.Decimal("123.45"),
        "nullable": decimal.Decimal("123.4500"),
    },
    note="no places: source scale survives; only places= changes scale",
)

sample(
    "decimal-float-input-is-str-converted",
    decimal_schema,
    {
        "amount": 0.1,
        "string_amount": 2.675,
        "rounded": 2.675,
        "half_up": 2.675,
        "nullable": 1e-05,
    },
    # float -> str(float) -> Decimal, so the float's repr is frozen in.
    {
        "amount": decimal.Decimal("0.1"),
        "string_amount": decimal.Decimal("2.675"),
        "rounded": decimal.Decimal("2.68"),
        "half_up": decimal.Decimal("2.68"),
        "nullable": decimal.Decimal("0.00001"),
    },
    {
        "amount": decimal.Decimal("0.1"),
        "string_amount": "2.675",
        "rounded": decimal.Decimal("2.68"),
        "half_up": decimal.Decimal("2.68"),
        "nullable": decimal.Decimal("0.00001"),
    },
    note="JSON numbers arrive as float; precision is limited by repr(float)",
)

sample(
    "decimal-explicit-null-vs-missing",
    decimal_schema,
    {"amount": None, "string_amount": None, "rounded": None, "half_up": None},
    missing_sentinel,
    missing_sentinel,
    expected_errors={
        "amount": ["Field may not be null."],
        "string_amount": ["Field may not be null."],
        "rounded": ["Field may not be null."],
        "half_up": ["Field may not be null."],
    },
    expected_valid_data={},
    note="explicit null fails unless allow_none; missing keys are simply absent",
)

sample(
    "decimal-allow-none-round-trip",
    decimal_schema,
    {"nullable": None},
    {"nullable": None},
    {"nullable": None},
    note="allow_none=True keeps explicit null through load and dump",
)

sample(
    "decimal-invalid-token",
    decimal_schema,
    {"amount": "abc"},
    missing_sentinel,
    missing_sentinel,
    expected_errors={"amount": ["Not a valid number."]},
    expected_valid_data={},
    note="non-numeric string is a validation error, not coercion",
)

sample(
    "decimal-quantize-and-rounding",
    decimal_schema,
    {
        "amount": "1E+5",
        "string_amount": "-0",
        "rounded": "2.665",
        "half_up": "2.665",
        "nullable": "100",
    },
    {
        "amount": decimal.Decimal("1E+5"),
        "string_amount": decimal.Decimal("-0"),
        "rounded": decimal.Decimal("2.66"),
        "half_up": decimal.Decimal("2.67"),
        "nullable": decimal.Decimal("100"),
    },
    {
        "amount": decimal.Decimal("1E+5"),
        "string_amount": "-0",
        "rounded": decimal.Decimal("2.66"),
        "half_up": decimal.Decimal("2.67"),
        "nullable": decimal.Decimal("100"),
    },
    note="default ROUND_HALF_EVEN vs explicit ROUND_HALF_UP; exponent form stays unless quantized",
)


# ---------------------------------------------------------------------------
# DateTime: timezone offsets preserved vs. normalized, plus format families
# ---------------------------------------------------------------------------

datetime_schema = DateTimeContractSchema()

sample(
    "datetime-iso-offset-preserved",
    datetime_schema,
    {"iso": "2024-03-01T12:34:56+05:30"},
    {"iso": dt.datetime(2024, 3, 1, 12, 34, 56, tzinfo=INDIA)},
    {"iso": "2024-03-01T12:34:56+05:30"},
    note="ISO offset survives load and dump verbatim",
)

sample(
    "datetime-iso-z-normalized-to-plus-00-00",
    datetime_schema,
    {"iso": "2024-03-01T12:34:56Z"},
    {"iso": dt.datetime(2024, 3, 1, 12, 34, 56, tzinfo=UTC)},
    {"iso": "2024-03-01T12:34:56+00:00"},
    note="trailing Z is accepted but dumped as +00:00",
)

sample(
    "datetime-iso-microseconds-and-negative-offset",
    datetime_schema,
    {"iso": "2024-03-01T12:34:56.123456-06:00"},
    {"iso": dt.datetime(2024, 3, 1, 12, 34, 56, 123456, tzinfo=US_CENTRAL)},
    {"iso": "2024-03-01T12:34:56.123456-06:00"},
    note="microseconds and negative offsets round-trip",
)

sample(
    "datetime-iso-naive-stays-naive",
    datetime_schema,
    {"iso": "2024-03-01T12:34:56"},
    {"iso": dt.datetime(2024, 3, 1, 12, 34, 56)},
    {"iso": "2024-03-01T12:34:56"},
    note="no timezone is added or removed by default",
)

sample(
    "datetime-rfc-format-family",
    datetime_schema,
    {"rfc": "Fri, 01 Mar 2024 12:34:56 -0000"},
    {"rfc": dt.datetime(2024, 3, 1, 12, 34, 56)},
    {"rfc": "Fri, 01 Mar 2024 12:34:56 -0000"},
    note="RFC822 -0000 parses to a naive datetime and dumps back as -0000",
)

sample(
    "datetime-epoch-formats-become-naive-utc",
    datetime_schema,
    {"epoch": 1709296496, "epoch_ms": 1709296496123},
    {
        "epoch": dt.datetime(2024, 3, 1, 12, 34, 56),
        "epoch_ms": dt.datetime(2024, 3, 1, 12, 34, 56, 123000),
    },
    {"epoch": 1709296496.0, "epoch_ms": 1709296496123.0},
    note="timestamps load as naive UTC datetimes and dump back as floats",
)

sample(
    "datetime-awareness-strict-fields",
    datetime_schema,
    {
        "naive": "2024-03-01T12:34:56Z",
        "aware": "2024-03-01T12:34:56",
        "utc_naive": "2024-03-01T12:34:56+05:30",
        "default_aware": "2024-03-01T12:34:56",
    },
    missing_sentinel,
    missing_sentinel,
    expected_errors={
        "naive": ["Not a valid naive datetime."],
        "aware": ["Not a valid aware datetime."],
    },
    expected_valid_data={
        "utc_naive": dt.datetime(2024, 3, 1, 7, 4, 56),
        "default_aware": dt.datetime(2024, 3, 1, 12, 34, 56, tzinfo=INDIA),
    },
    note="NaiveDateTime/AwareDateTime reject wrong awareness; with a timezone they convert instead",
)

sample(
    "datetime-invalid-token",
    datetime_schema,
    {"iso": "not-a-date"},
    missing_sentinel,
    missing_sentinel,
    expected_errors={"iso": ["Not a valid datetime."]},
    expected_valid_data={},
    note="unparseable strings raise the generic invalid-datetime message",
)


# ---------------------------------------------------------------------------
# Missing key vs. explicit null vs. load_default / dump_default
# ---------------------------------------------------------------------------

presence_schema = PresenceContractSchema()

sample(
    "presence-missing-key-is-omitted",
    presence_schema,
    {"amount": "1.00"},
    {
        "amount": decimal.Decimal("1.00"),
        "defaulted": decimal.Decimal("0.00"),
    },
    {
        "amount": decimal.Decimal("1.00"),
        "defaulted": decimal.Decimal("0.00"),
        "dump_fallback": "N/A",
        "dump_null": None,
    },
    note="absent load key -> key absent from result (unless load_default); absent dump attribute -> key absent (unless dump_default)",
)

sample(
    "presence-explicit-null-without-allow-none",
    presence_schema,
    {"amount": "1.00", "note": None},
    missing_sentinel,
    missing_sentinel,
    expected_errors={"note": ["Field may not be null."]},
    expected_valid_data={
        "amount": decimal.Decimal("1.00"),
        "defaulted": decimal.Decimal("0.00"),
    },
    note="null is an error for ordinary fields; partial valid_data is still returned",
)

sample(
    "presence-defaults-are-injected-on-both-directions",
    presence_schema,
    {},
    {"defaulted": decimal.Decimal("0.00")},
    {
        "defaulted": decimal.Decimal("0.00"),
        "dump_fallback": "N/A",
        "dump_null": None,
    },
    note="load_default fires when input key is absent; dump_default fires when internal attribute is absent",
)


# ---------------------------------------------------------------------------
# Nested List with data_key paths, read-only / write-only and unknown keys
# ---------------------------------------------------------------------------

nested_schema = NestedContractSchema()

sample(
    "nested-list-data-key-round-trip",
    nested_schema,
    {
        "orderId": 1,
        "secret": "write-only-value",
        "lineItems": [
            {
                "childId": 7,
                "price": "9.99",
                "when": "2024-01-01T00:00:00+09:00",
            }
        ],
        "amounts": ["1.50", None, "3"],
        "times": ["2024-01-01T00:00:00Z"],
        "tags": ["alpha", "beta"],
    },
    {
        "order_id": 1,
        "secret": "write-only-value",
        "line_items": [
            {
                "child_id": 7,
                "price": decimal.Decimal("9.99"),
                "when": dt.datetime(
                    2024, 1, 1, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=9))
                ),
            }
        ],
        "amounts": [decimal.Decimal("1.50"), None, decimal.Decimal("3")],
        "times": [dt.datetime(2024, 1, 1, 0, 0, tzinfo=UTC)],
        "tags": ["alpha", "beta"],
    },
    {
        "orderId": 1,
        "lineItems": [
            {
                "childId": 7,
                "price": "9.99",
                "when": "2024-01-01T00:00:00+09:00",
            }
        ],
        "amounts": [decimal.Decimal("1.50"), None, decimal.Decimal("3")],
        "times": ["2024-01-01T00:00:00+00:00"],
        "tags": ["alpha", "beta"],
    },
    note="data_key renames external keys; internal names differ; load_only secret never dumped; Z normalizes to +00:00",
)

sample(
    "nested-list-element-errors-are-indexed",
    nested_schema,
    {
        "orderId": 1,
        "lineItems": [
            {"childId": 7, "price": "9.99"},
            {"childId": "bad"},
        ],
        "amounts": ["oops", None],
        "times": ["not-a-date"],
    },
    missing_sentinel,
    missing_sentinel,
    expected_errors={
        "lineItems": {1: {"childId": ["Not a valid integer."]}},
        "amounts": {0: ["Not a valid number."]},
        "times": {0: ["Not a valid datetime."]},
    },
    expected_valid_data={
        "order_id": 1,
        "line_items": [
            {"child_id": 7, "price": decimal.Decimal("9.99")},
            {},
        ],
        "amounts": [None],
    },
    note="errors keyed by data_key and list index; valid elements survive in valid_data; empty-list partial result is dropped",
)

sample(
    "nested-missing-list-key-vs-null-vs-wrong-type",
    nested_schema,
    {"orderId": 1, "lineItems": None},
    missing_sentinel,
    missing_sentinel,
    expected_errors={"lineItems": ["Field may not be null."]},
    expected_valid_data={"order_id": 1},
    note="null list is rejected; an absent key would be omitted; a non-list reports 'Not a valid list.'",
)

sample(
    "nested-wrong-type-message",
    nested_schema,
    {"orderId": 1, "lineItems": "not-a-list"},
    missing_sentinel,
    missing_sentinel,
    expected_errors={"lineItems": ["Not a valid list."]},
    expected_valid_data={"order_id": 1},
    note="scalar input to a List field",
)

sample(
    "nested-required-and-dump-only-on-input",
    nested_schema,
    {"secret": "s", "computed": "client-sent", "lineItems": []},
    missing_sentinel,
    missing_sentinel,
    expected_errors={
        "orderId": ["Missing data for required field."],
        "computed": ["Unknown field."],
    },
    expected_valid_data={"secret": "s", "line_items": []},
    note="dump_only input is an unknown field under RAISE and never enters load data",
)

sample(
    "nested-unknown-raise-default",
    nested_schema,
    {"orderId": 2, "extra": 9},
    missing_sentinel,
    missing_sentinel,
    expected_errors={"extra": ["Unknown field."]},
    expected_valid_data={"order_id": 2},
    note="unknown=RAISE is the schema default; separate samples cover EXCLUDE and INCLUDE",
)

sample(
    "nested-unknown-exclude",
    NestedContractSchema(unknown=EXCLUDE),
    {"orderId": 2, "extra": 9},
    {"order_id": 2},
    {"orderId": 2},
    note="unknown=EXCLUDE drops the extra top-level key",
)

sample(
    "nested-unknown-include",
    NestedContractSchema(unknown=INCLUDE),
    {"orderId": 2, "extra": 9},
    {"order_id": 2, "extra": 9},
    {"orderId": 2},
    note="unknown=INCLUDE passes the raw key through on load only; dump still emits declared fields",
)

sample(
    "nested-list-child-missing-vs-null",
    nested_schema,
    {
        "orderId": 1,
        "lineItems": [
            {"childId": 1, "when": None},
            {"childId": 2},
        ],
    },
    {
        "order_id": 1,
        "line_items": [
            {"child_id": 1, "when": None},
            {"child_id": 2},
        ],
    },
    {
        "orderId": 1,
        "lineItems": [
            {"childId": 1, "when": None},
            {"childId": 2},
        ],
    },
    note="inside a nested list, explicit null is kept when allow_none=True; a missing child key stays absent",
)

sample(
    "nested-unknown-does-not-propagate-into-nested",
    nested_schema,
    {"orderId": 1, "lineItems": [{"childId": 1, "mystery": 42}]},
    missing_sentinel,
    missing_sentinel,
    expected_errors={"lineItems": {0: {"mystery": ["Unknown field."]}}},
    expected_valid_data={
        "order_id": 1,
        "line_items": [{"child_id": 1}],
    },
    note="nested schemas keep their own unknown setting instead of inheriting the parent's",
)

sample(
    "nested-dump-only-field-is-emitted-on-serialize",
    nested_schema,
    missing_sentinel,
    missing_sentinel,
    {"orderId": 3, "computed": "server-value"},
    dump_payload={"order_id": 3, "computed": "server-value", "secret": "hidden"},
    note="dump_only appears in dump; load_only secret is omitted from dump",
)


# ---------------------------------------------------------------------------
# Assertions: every expectation above is an independent literal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract", SAMPLES, ids=lambda c: c.id)
def test_contract_sample(contract: ContractSample) -> None:
    if contract.payload is missing_sentinel:
        dumped = contract.schema.dump(contract.dump_payload)
        assert dumped == contract.expected_dump
        return

    if contract.should_fail:
        with pytest.raises(ValidationError) as excinfo:
            contract.schema.load(contract.payload)
        error = excinfo.value
        assert error.messages == contract.expected_errors
        assert error.valid_data == contract.expected_valid_data
        return

    loaded = contract.schema.load(contract.payload)
    assert loaded == contract.expected_load

    dump_source = (
        loaded if contract.dump_payload is missing_sentinel else contract.dump_payload
    )
    dumped = contract.schema.dump(dump_source)
    assert dumped == contract.expected_dump


def test_sample_ids_are_unique() -> None:
    ids = [contract.id for contract in SAMPLES]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Sample table for the migration team (input / actual output / errors)
# ---------------------------------------------------------------------------


def _md_cell(value: Any) -> str:
    if value is missing_sentinel:
        return "—"
    text = repr(value)
    return "`" + text.replace("|", "\\|").replace("\n", " ") + "`"


def render_sample_table() -> str:
    header = (
        "| Sample | Input | load() result | dump() result | Error | Note |\n"
        "| --- | --- | --- | --- | --- | --- |"
    )
    rows = [header]
    for contract in SAMPLES:
        if contract.should_fail:
            load_cell = _md_cell(contract.expected_valid_data) + " (valid_data)"
            dump_cell = "—"
            error_cell = _md_cell(contract.expected_errors)
        else:
            load_cell = _md_cell(contract.expected_load)
            dump_cell = _md_cell(contract.expected_dump)
            error_cell = "—"
        rows.append(
            " | ".join(
                [
                    "",
                    contract.id,
                    _md_cell(contract.payload),
                    load_cell,
                    dump_cell,
                    error_cell,
                    contract.note,
                    "",
                ]
            )
        )
    return "\n".join(rows)


DOCUMENT_HEADER = """\
# Marshmallow 4.4.0 migration contract samples

Generated snapshot of `tests/test_migration_contract.py`. The pytest module is
the source of truth; regenerate this file after changing it:

```sh
.venv/bin/python -m tests.test_migration_contract > tests/migration_contract_samples.md
```

Each row shows the external JSON-style input, the independent expected result
of `Schema.load`, the expected result of `Schema.dump`, and the
`ValidationError` payload (with `valid_data`) when loading fails. `—` means the
column does not apply (e.g. dump is skipped for failed loads).
"""


def render_document() -> str:
    return DOCUMENT_HEADER + "\n" + render_sample_table()


if __name__ == "__main__":
    print(render_document())

