# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marshmallow",
# ]
# ///
"""Accept historical external keys on load while always dumping the current key."""

from marshmallow import Schema, ValidationError, fields


class StationSchema(Schema):
    # New producers send ``station_id``. Old producers send ``stationId`` or
    # ``sid`` for the next six months. Both are read-only aliases.
    station_id = fields.Int(load_aliases=("stationId", "sid"))
    name = fields.Str()


schema = StationSchema()

CASES = [
    ("new: current name", {"station_id": 101, "name": "hub-a"}),
    ("old: first historical name", {"stationId": 102, "name": "hub-b"}),
    ("old: older historical name", {"sid": 103, "name": "hub-c"}),
    ("mixed: equal values", {"station_id": 104, "sid": 104, "name": "hub-d"}),
    ("mixed: conflicting values", {"station_id": 105, "sid": 999, "name": "hub-e"}),
    ("alias + genuinely unknown key", {"sid": 106, "mystery": 1}),
]


def describe(data: dict) -> str:
    try:
        loaded = schema.load(data)
    except ValidationError as error:
        return f"ERROR {error.messages} VALID {error.valid_data}"
    return f"LOAD {loaded} -> DUMP {schema.dump(loaded)}"


if __name__ == "__main__":
    for label, data in CASES:
        print(f"{label:34} {data}")
        print(f"{'':34} {describe(data)}")
