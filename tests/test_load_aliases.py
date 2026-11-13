"""Tests for read-only historical field names (``load_aliases``)."""
# mypy: disable-error-code="arg-type"
import pytest

from marshmallow import EXCLUDE, INCLUDE, RAISE, Schema, fields, post_load, pre_load
from marshmallow.exceptions import ValidationError


class StationSchema(Schema):
    station_id = fields.Int(load_aliases=("stationId", "sid"))
    name = fields.Str()


class TestLoadAliases:
    def test_current_name_still_loads(self):
        assert StationSchema().load({"station_id": 7, "name": "hub"}) == {
            "station_id": 7,
            "name": "hub",
        }

    def test_each_alias_loads_under_current_name(self):
        for payload in (
            {"stationId": 7, "name": "hub"},
            {"sid": 7, "name": "hub"},
        ):
            assert StationSchema().load(payload) == {
                "station_id": 7,
                "name": "hub",
            }

    def test_dump_never_emits_aliases(self):
        loaded = StationSchema().load({"sid": 7, "name": "hub"})
        assert StationSchema().dump(loaded) == {"station_id": 7, "name": "hub"}
        assert StationSchema().dumps(loaded, sort_keys=True) == (
            '{"name": "hub", "station_id": 7}'
        )

    def test_alias_works_with_data_key(self):
        class S(Schema):
            station_id = fields.Int(data_key="station_id_v2", load_aliases=("sid",))

        assert S().load({"sid": 1}) == {"station_id": 1}
        assert S().dump({"station_id": 1}) == {"station_id_v2": 1}

    def test_duplicate_alias_names_are_deduped(self):
        class S(Schema):
            station_id = fields.Int(load_aliases=("sid", "sid"))

        assert S().load({"sid": 3}) == {"station_id": 3}

    def test_non_string_alias_is_rejected(self):
        with pytest.raises(ValueError, match="load_aliases"):
            fields.Int(load_aliases=(1,))

    def test_alias_equal_to_canonical_key_is_ignored(self):
        class S(Schema):
            station_id = fields.Int(load_aliases=("station_id",))

        assert S().load({"station_id": 4}) == {"station_id": 4}

    def test_mixed_names_with_equal_values_accepted(self):
        assert StationSchema().load(
            {"station_id": 7, "stationId": 7, "sid": 7, "name": "hub"}
        ) == {"station_id": 7, "name": "hub"}

    def test_mixed_names_with_conflicting_values_raises_field_error(self):
        with pytest.raises(ValidationError) as exc_info:
            StationSchema().load({"station_id": 7, "sid": 8})
        messages = exc_info.value.messages
        assert set(messages) == {"station_id"}
        assert "station_id" in messages["station_id"][0]
        assert "sid" in messages["station_id"][0]
        assert exc_info.value.valid_data == {}

    def test_conflict_between_two_aliases(self):
        with pytest.raises(ValidationError) as exc_info:
            StationSchema().load({"stationId": 7, "sid": 8})
        assert set(exc_info.value.messages) == {"station_id"}

    def test_conflict_message_lists_every_name_involved(self):
        class S(Schema):
            station_id = fields.Int(load_aliases=("a", "b", "c"))

        with pytest.raises(ValidationError) as exc_info:
            S().load({"a": 1, "b": 2, "c": 1})
        message = exc_info.value.messages["station_id"][0]
        for name in ("a", "b", "c"):
            assert name in message

    def test_conflict_is_checked_on_raw_values_before_conversion(self):
        # "7" and 7 would deserialize to the same integer; as raw input they
        # differ, so the conflict must still be reported.
        class S(Schema):
            station_id = fields.Int(load_aliases=("sid",))

        with pytest.raises(ValidationError) as exc_info:
            S().load({"station_id": "7", "sid": 7})
        assert "station_id" in exc_info.value.messages

    def test_equal_raw_values_pass_even_if_both_fail_conversion(self):
        # Same raw value under both names -> no alias conflict; the normal
        # field-level conversion error is the only error raised.
        class S(Schema):
            station_id = fields.Int(load_aliases=("sid",))

        with pytest.raises(ValidationError) as exc_info:
            S().load({"station_id": "not-an-int", "sid": "not-an-int"})
        message = exc_info.value.messages["station_id"][0]
        assert "Conflicting" not in message

    def test_conflict_suppresses_required_and_load_default(self):
        class RequiredSchema(Schema):
            station_id = fields.Int(required=True, load_aliases=("sid",))

        with pytest.raises(ValidationError) as exc_info:
            RequiredSchema().load({"station_id": 1, "sid": 2})
        assert len(exc_info.value.messages["station_id"]) == 1

        class DefaultSchema(Schema):
            station_id = fields.Int(load_default=42, load_aliases=("sid",))

        with pytest.raises(ValidationError) as exc_info:
            DefaultSchema().load({"station_id": 1, "sid": 2})
        assert exc_info.value.valid_data == {}

    def test_consumed_alias_is_not_reported_as_unknown(self):
        for unknown in (RAISE, INCLUDE, EXCLUDE):
            result = StationSchema(unknown=unknown).load({"sid": 7})
            assert result == {"station_id": 7}

    def test_truly_unknown_field_is_not_swallowed_by_aliases(self):
        with pytest.raises(ValidationError) as exc_info:
            StationSchema().load({"sid": 7, "mystery": 1})
        assert exc_info.value.messages == {"mystery": ["Unknown field."]}

        assert StationSchema(unknown=INCLUDE).load({"sid": 7, "mystery": 1}) == {
            "station_id": 7,
            "mystery": 1,
        }
        assert StationSchema(unknown=EXCLUDE).load({"sid": 7, "mystery": 1}) == {
            "station_id": 7
        }

    def test_alias_and_genuine_unknown_coexist_on_conflict(self):
        with pytest.raises(ValidationError) as exc_info:
            StationSchema().load({"station_id": 1, "sid": 2, "mystery": 3})
        assert set(exc_info.value.messages) == {"station_id", "mystery"}

    def test_nested_schemas_resolve_aliases(self):
        class Inner(Schema):
            station_id = fields.Int(required=True, load_aliases=("stationId",))

        class Outer(Schema):
            station_id = fields.Int(load_aliases=("sid",))
            inner = fields.Nested(Inner)
            items = fields.List(fields.Nested(Inner))

        result = Outer().load(
            {
                "sid": 1,
                "inner": {"stationId": 2},
                "items": [{"stationId": 3}, {"station_id": 4}],
            }
        )
        assert result == {
            "station_id": 1,
            "inner": {"station_id": 2},
            "items": [{"station_id": 3}, {"station_id": 4}],
        }

    def test_nested_conflict_is_located_in_path(self):
        class Inner(Schema):
            station_id = fields.Int(load_aliases=("stationId",))

        class Outer(Schema):
            items = fields.List(fields.Nested(Inner))

        with pytest.raises(ValidationError) as exc_info:
            Outer().load(
                {"items": [{"stationId": 1}, {"station_id": 2, "stationId": 9}]}
            )
        messages = exc_info.value.messages
        assert set(messages) == {"items"}
        assert set(messages["items"]) == {1}
        assert set(messages["items"][1]) == {"station_id"}
        assert "Conflicting" in messages["items"][1]["station_id"][0]

    def test_many_loads_with_aliases_and_indexed_conflicts(self):
        data = [{"sid": 1}, {"station_id": 2, "sid": 3}]
        assert StationSchema().load(data[:1], many=True) == [{"station_id": 1}]
        with pytest.raises(ValidationError) as exc_info:
            StationSchema().load(data, many=True)
        messages = exc_info.value.messages
        assert set(messages) == {1}
        assert set(messages[1]) == {"station_id"}
        assert "Conflicting" in messages[1]["station_id"][0]

    def test_partial_load_with_aliases(self):
        assert StationSchema().load({"sid": 7}, partial=True) == {"station_id": 7}
        assert StationSchema().load({}, partial=True) == {}

    def test_partial_collection_of_field_names(self):
        class S(Schema):
            station_id = fields.Int(required=True, load_aliases=("sid",))
            name = fields.Str(required=True)

        assert S().load({"sid": 7}, partial=("name",)) == {"station_id": 7}

    def test_alias_collision_with_canonical_key_raises_at_schema_init(self):
        class S(Schema):
            station_id = fields.Int()
            other = fields.Int(load_aliases=("station_id",))

        with pytest.raises(ValueError, match="collides"):
            S()

    def test_alias_collision_between_fields_raises_at_schema_init(self):
        class S(Schema):
            station_id = fields.Int(load_aliases=("legacy_id",))
            other = fields.Int(load_aliases=("legacy_id",))

        with pytest.raises(ValueError, match="collides"):
            S()

    def test_alias_on_dump_only_field_is_ignored_for_loading(self):
        class S(Schema):
            station_id = fields.Int(dump_only=True, load_aliases=("sid",))

        with pytest.raises(ValidationError) as exc_info:
            S().load({"sid": 1})
        assert exc_info.value.messages == {"sid": ["Unknown field."]}

    def test_pre_load_sees_raw_aliased_input(self):
        seen = {}

        class S(Schema):
            station_id = fields.Int(load_aliases=("sid",))

            @pre_load
            def remember(self, data, **kwargs):
                seen.update(data)
                return data

        S().load({"sid": 5})
        assert seen == {"sid": 5}

    def test_post_load_runs_only_without_conflicts(self):
        class S(Schema):
            station_id = fields.Int(load_aliases=("sid",))

            @post_load
            def wrap(self, data, **kwargs):
                return {"wrapped": data}

        assert S().load({"sid": 5}) == {"wrapped": {"station_id": 5}}
        with pytest.raises(ValidationError):
            S().load({"station_id": 1, "sid": 2})

    def test_input_mapping_is_not_mutated(self):
        payload = {"sid": 7, "name": "hub"}
        StationSchema().load(payload)
        assert payload == {"sid": 7, "name": "hub"}

    def test_mapping_with_custom_dict_class(self):
        from collections import OrderedDict

        class OrderedSchema(Schema):
            dict_class = OrderedDict

            station_id = fields.Int(load_aliases=("sid",))

        result = OrderedSchema().load(OrderedDict([("sid", 9)]))
        assert result == {"station_id": 9}
        assert list(result) == ["station_id"]

    def test_custom_conflict_error_message(self):
        class S(Schema):
            station_id = fields.Int(
                load_aliases=("sid",),
                error_messages={"alias_conflict": "pick one of: {aliases}"},
            )

        with pytest.raises(ValidationError) as exc_info:
            S().load({"station_id": 1, "sid": 2})
        assert exc_info.value.messages == {
            "station_id": ["pick one of: station_id, sid"]
        }

    def test_only_option_keeps_alias_for_selected_field(self):
        class S(Schema):
            station_id = fields.Int(load_aliases=("sid",))
            name = fields.Str()

        result = S(only=("station_id",)).load({"sid": 5, "name": "x"}, unknown=EXCLUDE)
        assert result == {"station_id": 5}

    def test_aliases_are_inherited_by_subclass_schemas(self):
        class ChildSchema(StationSchema):
            extra = fields.Bool()

        assert ChildSchema().load({"sid": 6, "extra": True}) == {
            "station_id": 6,
            "extra": True,
        }
        assert ChildSchema().dump({"station_id": 6, "extra": True}) == {
            "station_id": 6,
            "extra": True,
        }

    def test_meta_many_loads_with_aliases(self):
        class S(Schema):
            station_id = fields.Int(load_aliases=("sid",))

            class Meta:
                many = True

        assert S().load([{"sid": 1}, {"station_id": 2}]) == [
            {"station_id": 1},
            {"station_id": 2},
        ]

    def test_single_string_alias_is_accepted(self):
        class S(Schema):
            station_id = fields.Int(load_aliases="sid")

        assert S().load({"sid": 8}) == {"station_id": 8}
