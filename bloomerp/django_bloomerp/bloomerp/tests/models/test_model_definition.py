from django.test import SimpleTestCase
from pydantic import ValidationError

from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailTab,
    DetailTabFolder,
    DetailViewSettings,
)
from bloomerp.workspaces.text_tile.model import TextTileConfig


class BloomerpModelConfigTileTests(SimpleTestCase):
    def test_model_config_accepts_concrete_tile_configs(self):
        """
        Use case: A model declares a reusable concrete tile configuration.
        Expected result: The model config retains its metadata and type-specific payload.
        """
        # 1. Define a text tile on a model configuration.
        tile = TextTileConfig(
            id="summary",
            name="Summary",
            description="A model summary.",
            icon="fa-solid fa-align-left",
            markdown="Model summary",
        )
        config = BloomerpModelConfig(tiles=[tile])

        # 2. Verify the concrete instance remains available through the config.
        self.assertIs(config.tiles[0], tile)
        self.assertEqual(config.tiles[0].markdown, "Model summary")

        # 3. Verify serialization retains both base metadata and subtype fields.
        serialized_tile = config.model_dump()["tiles"][0]
        self.assertEqual(serialized_tile["id"], "summary")
        self.assertEqual(serialized_tile["name"], "Summary")
        self.assertEqual(serialized_tile["markdown"], "Model summary")

    def test_model_config_uses_an_independent_empty_tile_list(self):
        """
        Use case: Multiple model configurations are created without tiles.
        Expected result: Each configuration receives its own empty tile list.
        """
        # 1. Create two model configurations with default tile lists.
        first = BloomerpModelConfig()
        second = BloomerpModelConfig()

        # 2. Mutate one list and verify the other configuration is unaffected.
        first.tiles.append(TextTileConfig(markdown="Only on first"))
        self.assertEqual(len(first.tiles), 1)
        self.assertEqual(second.tiles, [])

    def test_model_config_requires_unique_tile_ids(self):
        """
        Use case: A model declares tiles that workspaces can reference by ID.
        Expected result: Missing and duplicate IDs are rejected during configuration.
        """
        # 1. Verify a declarative tile cannot omit its stable ID.
        with self.assertRaisesRegex(ValidationError, "must have an id"):
            BloomerpModelConfig(
                tiles=[TextTileConfig(name="Missing ID", markdown="")]
            )

        # 2. Verify IDs must be unique within the model configuration.
        with self.assertRaisesRegex(ValidationError, "Duplicate tile id 'summary'"):
            BloomerpModelConfig(
                tiles=[
                    TextTileConfig(id="summary", markdown="First"),
                    TextTileConfig(id="summary", markdown="Second"),
                ]
            )


class DetailViewSettingsTests(SimpleTestCase):
    def test_detail_view_settings_accept_declarative_default_tabs(self):
        """
        Use case: A model declares an ordered default detail-tab layout.
        Expected result: Tabs and folders retain their concrete types and payloads.
        """
        # 1. Define a default layout with a top-level tab and folder.
        settings = DetailViewSettings(
            default_tabs=[
                DetailTab(name=" Overview ", url=" /todos/{{pk}}/ "),
                DetailTabFolder(
                    name="Related",
                    tabs=[
                        DetailTab(
                            name="Initiative",
                            url="/todos/{{pk}}/initiative/",
                        )
                    ],
                ),
            ]
        )

        # 2. Confirm normalization and the easy-to-consume concrete models.
        self.assertEqual(settings.default_tabs[0].name, "Overview")
        self.assertEqual(settings.default_tabs[0].url, "/todos/{{pk}}/")
        self.assertIsInstance(settings.default_tabs[1], DetailTabFolder)
        self.assertEqual(settings.default_tabs[1].tabs[0].name, "Initiative")

        # 3. Confirm absent and explicitly empty overrides remain distinguishable.
        self.assertIsNone(DetailViewSettings().default_tabs)
        self.assertEqual(DetailViewSettings(default_tabs=[]).default_tabs, [])

    def test_detail_view_settings_reject_invalid_default_tabs(self):
        """
        Use case: A model declares malformed default tabs or nested folders.
        Expected result: Configuration validation fails during application startup.
        """
        # 1. Reject unsupported URL templates.
        with self.assertRaisesRegex(ValidationError, "Only the.*pk.*placeholder"):
            DetailViewSettings(
                default_tabs=[
                    DetailTab(name="Invalid", url="/todos/{{user_id}}/")
                ]
            )

        # 2. Reject folders inside folders through the concrete child type.
        with self.assertRaises(ValidationError):
            DetailViewSettings(
                default_tabs=[
                    {
                        "name": "Parent",
                        "tabs": [
                            {
                                "name": "Nested",
                                "tabs": [],
                            }
                        ],
                    }
                ]
            )
