"""Re-runnable operation counters for repeated deep-schema construction.

Counts work with the unmodified code and the optimized code alike; only the
numbers change. No timing is involved.
"""
from __future__ import annotations

import copy
import sys

import marshmallow.fields as mf
import marshmallow.schema as ms
from marshmallow import Schema, fields
from marshmallow.fields import Field, Nested


class Counters:
    def __init__(self) -> None:
        self.deepcopy_calls = 0
        self.field_copies = 0
        self.schema_inits = 0
        self.nested_accesses = 0
        self.registry_lookups = 0


COUNTERS = Counters()
_orig_deepcopy = copy.deepcopy
_orig_schema_init = Schema.__init__
_orig_nested_schema = Nested.schema.fget
_orig_get_class = ms.class_registry.get_class


def install() -> None:
    def counted_deepcopy(value, *args, **kwargs):
        COUNTERS.deepcopy_calls += 1
        return _orig_deepcopy(value, *args, **kwargs)

    if hasattr(mf, "copy_field"):
        orig_copy_field = mf.copy_field

        def counted_copy_field(field, memo=None):
            COUNTERS.field_copies += 1
            return orig_copy_field(field, memo)

        mf.copy_field = counted_copy_field
        ms.ma_fields.copy_field = counted_copy_field
    else:
        orig_field_deepcopy = Field.__deepcopy__

        def counted_field_deepcopy(self, memo):
            COUNTERS.field_copies += 1
            return orig_field_deepcopy(self, memo)

        Field.__deepcopy__ = counted_field_deepcopy

    def counted_schema_init(self, *args, **kwargs):
        COUNTERS.schema_inits += 1
        return _orig_schema_init(self, *args, **kwargs)

    def counted_nested_schema(self):
        COUNTERS.nested_accesses += 1
        return _orig_nested_schema(self)

    def counted_get_class(*args, **kwargs):
        COUNTERS.registry_lookups += 1
        return _orig_get_class(*args, **kwargs)

    copy.deepcopy = counted_deepcopy
    mf.copy.deepcopy = counted_deepcopy
    if hasattr(ms, "copy"):
        ms.copy.deepcopy = counted_deepcopy
    Schema.__init__ = counted_schema_init
    Nested.schema = property(counted_nested_schema)
    ms.class_registry.get_class = counted_get_class
    mf.class_registry.get_class = counted_get_class


def snapshot() -> tuple[int, ...]:
    return (
        COUNTERS.deepcopy_calls,
        COUNTERS.field_copies,
        COUNTERS.schema_inits,
        COUNTERS.nested_accesses,
        COUNTERS.registry_lookups,
    )


def delta(before: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(a - b for a, b in zip(snapshot(), before, strict=True))


# Small, deep schema (4 levels; Nested and List(Nested) at each inner level).
class L4(Schema):
    a = fields.Str()
    b = fields.Int()
    c = fields.Raw()
    d = fields.Bool()


class L3(Schema):
    id = fields.Int()
    name = fields.Str()
    meta = fields.Nested(L4)
    tags = fields.List(fields.Nested(L4))


class L2(Schema):
    id = fields.Int()
    title = fields.Str()
    child = fields.Nested(L3)
    items = fields.List(fields.Nested(L3))


class L1(Schema):
    id = fields.Int()
    name = fields.Str()
    section = fields.Nested(L2)
    parts = fields.List(fields.Nested(L2))


class Node(Schema):
    value = fields.Int()
    children = fields.List(fields.Nested(lambda: Node, many=True))


class CustomField(fields.Field):
    def _serialize(self, value, attr, obj, **kwargs):
        return None if value is None else str(value)


class WithCustom(Schema):
    id = fields.Int()
    custom = fields.List(CustomField())
    nested = fields.Nested(L4)


class RegistryLeaf(Schema):
    name = fields.Str(required=True)
    amount = fields.Int(required=True)


class RegistryRoot(Schema):
    leaf = fields.Nested("RegistryLeaf")
    leaves = fields.List(fields.Nested("RegistryLeaf"))


class InstanceParam(Schema):
    id = fields.Int()
    note = fields.Str()


class InstanceRoot(Schema):
    item = fields.Nested(InstanceParam(only=("id",)), exclude=("note",))


FULL_OBJ = {
    "id": 1,
    "name": "x",
    "section": {
        "id": 2,
        "title": "t",
        "child": {
            "id": 3,
            "name": "n",
            "meta": {"a": "s", "b": 1},
            "tags": [{"a": "s"}],
        },
        "items": [
            {
                "id": 4,
                "title": "u",
                "child": {"id": 5, "name": "v", "meta": {"a": "w"}, "tags": []},
                "items": [],
            }
        ],
    },
    "parts": [
        {
            "id": 6,
            "title": "p",
            "child": {"id": 7, "name": "q", "meta": {"a": "r"}, "tags": []},
            "items": [],
        }
    ],
}

ONLY_A = ("id", "section.id", "section.title", "section.child.name")
ONLY_B = ("name", "parts.id", "parts.child.name", "parts.child.meta.a")

HEADERS = ("deepcopy", "field_copy", "schema_init", "nested.schema", "registry")


def report(label: str, before: tuple[int, ...]) -> tuple[int, ...]:
    values = delta(before)
    print(f"{label:42s} " + " ".join(f"{h}={v}" for h, v in zip(HEADERS, values, strict=True)))
    return values


def main() -> None:
    install()

    b = snapshot()
    L1()
    construct = report("single L1() construction", b)

    b = snapshot()
    L1().dump(FULL_OBJ)
    full = report("single L1() + full dump", b)

    b = snapshot()
    for _ in range(20):
        L1().dump(FULL_OBJ)
    etl = report("20x fresh L1() + full dump (ETL loop)", b)
    assert tuple(x * 20 for x in full) == etl

    b = snapshot()
    Node().dump({"value": 1, "children": [{"value": 2}]})
    report("recursive lambda Nested construct+dump", b)

    b = snapshot()
    WithCustom().dump(
        {"id": 1, "custom": [1, 2], "nested": {"a": "x", "b": 2, "c": 3, "d": True}}
    )
    report("custom Field subclass construct+dump", b)

    b = snapshot()
    RegistryRoot().dump({"leaf": {"name": "n", "amount": 3}, "leaves": []})
    report("string-registry Nested construct+dump", b)

    b = snapshot()
    instance_result = InstanceRoot().dump({"item": {"id": 9, "note": "hi"}})
    report("Nested(schema instance) construct+dump", b)
    assert instance_result == {"item": {"id": 9}}

    # Two partitions in parallel with different `only` options: separate
    # schema instances, shared classes, interleaved usage.
    partition_a = L1(only=ONLY_A)
    partition_b = L1(only=ONLY_B)
    b = snapshot()
    result_a = partition_a.dump(FULL_OBJ)
    result_b = partition_b.dump(FULL_OBJ)
    report("two partitions (different only) first dump", b)

    print()
    print("partition A result:", result_a)
    print("partition B result:", result_b)
    assert list(result_a) == ["id", "section"]
    assert result_a["section"] == {"id": 2, "title": "t", "child": {"name": "n"}}
    assert list(result_b) == ["name", "parts"]
    assert result_b["parts"][0]["child"] == {"name": "q", "meta": {"a": "r"}}

    # No mutable Field sharing across the parallel instances.
    assert partition_a.fields["id"] is not partition_b.fields["name"]
    partition_a.fields["id"].load_only = True
    assert partition_b.dump_fields.get("id") is None
    print("\nisolation OK: parallel only-options use distinct Field instances")


if __name__ == "__main__":
    sys.exit(main())
