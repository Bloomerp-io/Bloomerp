"""Analytics authoring schemas describe complete tiles without changing editor validation."""

from copy import deepcopy
from typing import Any
from unittest.mock import patch

from django.forms import CharField
from django.test import SimpleTestCase
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from bloomerp.workspaces.analytics_tile.model import (
    AnalyticsTileConfig, AnalyticsTileType, OptionDefinition,
)


class TestAnalyticsTileSchema(SimpleTestCase):
    """Check the exported schema directly, outside Django model lifecycle scenarios."""

    def payloads(self) -> list[dict[str, Any]]:
        """Return representative complete configurations for every supported subtype."""
        return [
            {"query": "SELECT 1 AS total", "type": "KPI", "fields": {
                "value": [{"name": "total", "opts": {"aggregator": "FIRST", "formatter": "NONE"}}],
            }},
            {"query": "SELECT 1 AS total", "type": "TABLE", "fields": {
                "columns": [{"name": "total", "opts": {"label": "Total"}}],
            }, "opts": {"page_size": "25", "size": "M"}},
            {"query": "SELECT 'Sales' AS department, 1 AS total", "type": "TWO_DIM_CHART", "fields": {
                "x_axis": [{"name": "department"}], "y_axis": [{"name": "total"}],
            }, "opts": {"chart_type": "bar", "stacked": False}},
            {"query": "SELECT 'Sales' AS department, 1 AS total", "type": "PIE_CHART", "fields": {
                "labels": [{"name": "department"}], "values": [{"name": "total"}],
            }, "opts": {"show_legend": True, "legend_position": "right"}},
        ]

    def test_supported_tiles_match_exactly_one_branch(self) -> None:
        """Use case: Export both schema modes for all supported tiles.
        Expected result: Each complete tile matches exactly one subtype branch.
        """
        # 1. Check both export modes are valid JSON Schemas.
        for mode in ("validation", "serialization"):
            schema = AnalyticsTileConfig.model_json_schema(mode=mode)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            self.assertEqual(
                {branch["properties"]["type"]["const"] for branch in schema["oneOf"]},
                {item.value.key for item in AnalyticsTileType},
            )
            # 2. Validate complete examples and their unambiguous subtype selection.
            for payload in self.payloads():
                with self.subTest(mode=mode, subtype=payload["type"]):
                    validator.validate(payload)
                    self.assertEqual(sum(
                        Draft202012Validator(branch).is_valid(payload)
                        for branch in schema["oneOf"]
                    ), 1)

    def test_inaccurate_configurations_are_rejected_by_schema(self) -> None:
        """Use case: An agent submits unsupported slots, choices or cardinalities.
        Expected result: The authoring schema rejects each inaccurate configuration.
        """
        # 1. Build incorrect configurations from otherwise valid examples.
        kpi, table, chart, pie = self.payloads()
        invalid = [deepcopy(kpi) for _ in range(4)]
        invalid[0]["type"] = "MAP"
        invalid[1]["fields"] = {}
        invalid[2]["fields"]["value"] = []
        invalid[3]["fields"]["value"][0]["opts"]["aggregator"] = "invented"
        table["opts"]["page_size"] = "1000"
        chart["fields"]["x_axis"].append({"name": "total"})
        pie["fields"]["value"] = [{"name": "total"}]
        wrong_option = deepcopy(kpi)
        wrong_option["opts"] = {"chart_type": "bar"}
        invalid.extend([table, chart, pie, wrong_option])
        # 2. Check the schema rejects each invalid payload.
        validator = Draft202012Validator(AnalyticsTileConfig.model_json_schema())
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertFalse(validator.is_valid(payload))

    def test_live_definitions_and_type_dependent_choices_are_exported(self) -> None:
        """Use case: Definitions change after an earlier schema export.
        Expected result: Later exports include new options and all typed choices.
        """
        # 1. Export once, then temporarily add a declared option.
        AnalyticsTileConfig.model_json_schema()
        definition = AnalyticsTileType.KPI.value
        option = OptionDefinition("custom_label", "Custom label", "A new display label.", CharField)
        with patch.object(definition, "opts", [*definition.opts, option]):
            schema = AnalyticsTileConfig.model_json_schema()
        # 2. Check the live option and numeric aggregation metadata.
        branch = next(item for item in schema["oneOf"] if item["properties"]["type"]["const"] == "KPI")
        self.assertEqual(branch["properties"]["opts"]["properties"]["custom_label"]["description"], "A new display label.")
        aggregator = branch["properties"]["fields"]["properties"]["value"]["items"]["properties"]["opts"]["properties"]["aggregator"]
        self.assertIn("SUM", aggregator["enum"])
        self.assertIn("SUM", aggregator["x-choices-by-field-type"]["numeric"])
        self.assertNotIn("SUM", aggregator["x-choices-by-field-type"]["text"])

    def test_nested_schema_keeps_hidden_metadata_and_references_valid(self) -> None:
        """Use case: A consumer embeds analytics config inside another Pydantic model.
        Expected result: References resolve and shared tile metadata stays hidden.
        """
        # 1. Export the schema through a containing model.
        class Container(BaseModel):
            """Wrap a tile to exercise Pydantic's nested schema references."""

            tile: AnalyticsTileConfig

        schema = Container.model_json_schema()
        # 2. Validate a nested payload and inspect the referenced configuration.
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate({"tile": self.payloads()[0]})
        config_schema = schema["$defs"]["AnalyticsTileConfig"]
        self.assertTrue({"id", "name", "description", "icon"}.isdisjoint(config_schema["properties"]))

    def test_editor_drafts_remain_accepted_at_runtime(self) -> None:
        """Use case: The tile editor starts with an incomplete analytics draft.
        Expected result: Schema generation does not tighten runtime validation yet.
        """
        # 1. Generate the complete authoring schema.
        AnalyticsTileConfig.model_json_schema()
        # 2. Confirm the existing empty editor draft still round-trips.
        config = AnalyticsTileConfig.get_default()
        self.assertEqual(config.fields, {})
        self.assertEqual(AnalyticsTileConfig.model_validate(config.model_dump()), config)
