from django.test import SimpleTestCase
from pydantic import ValidationError

from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.definition import (
    BloomerpModelConfig,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
)
from bloomerp.models.project_management.todo import Todo

from bloomerp.models.definition import (
    DetailTab,
    DetailTabFolder,
    DetailTabsConfiguration,
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


class BloomerpModelConfigDataViewTests(SimpleTestCase):
    def test_model_view_settings_accept_multiple_typed_default_dataviews(self):
        """
        Use case: A model declares multiple developer-friendly default data views.
        Expected result: Pydantic retains each concrete setup and its field names.
        """
        # 1. Define a selected Kanban view and an optional table view.
        settings = ModelViewSettings(
            default_dataviews=[
                KanbanDataView(
                    name="Workflow",
                    display_fields=["title", "priority"],
                    group_by_field="status",
                ),
                TableDataView(
                    name="All records",
                    is_default=False,
                    display_fields=["title", "status"],
                    sort_field="title",
                ),
            ]
        )

        # 2. Verify the concrete types and declarative field names are retained.
        self.assertIsInstance(settings.default_dataviews[0], KanbanDataView)
        self.assertEqual(settings.default_dataviews[0].group_by_field, "status")
        self.assertIsInstance(settings.default_dataviews[1], TableDataView)
        self.assertEqual(settings.default_dataviews[1].sort_field, "title")

    def test_model_view_settings_require_one_unique_default_dataview(self):
        """
        Use case: A developer misconfigures multiple model data views.
        Expected result: Duplicate names and ambiguous selections fail validation.
        """
        # 1. Verify multiple selected defaults are rejected.
        with self.assertRaisesRegex(ValidationError, "Exactly one configured"):
            ModelViewSettings(
                default_dataviews=[
                    KanbanDataView(name="Workflow"),
                    TableDataView(name="All records"),
                ]
            )

        # 2. Verify duplicate preference names are rejected.
        with self.assertRaisesRegex(ValidationError, "names must be unique"):
            ModelViewSettings(
                default_dataviews=[
                    KanbanDataView(name="Workflow"),
                    TableDataView(name="Workflow", is_default=False),
                ]
            )

    def test_todo_model_demonstrates_kanban_and_table_defaults(self):
        """
        Use case: A developer needs a concrete example of the new capability.
        Expected result: Todo declares a Kanban workflow and a secondary table view.
        """
        # 1. Read the Todo model's configured data views.
        data_views = Todo.bloomerp_config.model_view_settings.default_dataviews

        # 2. Verify the Kanban setup is selected and grouped by status.
        self.assertEqual(data_views[0].name, "Todo workflow")
        self.assertTrue(data_views[0].is_default)
        self.assertEqual(data_views[0].group_by_field, "status")

        # 3. Verify the table remains available as an alternative setup.
        self.assertEqual(data_views[1].name, "All todos")
        self.assertFalse(data_views[1].is_default)
        
    
class DetailViewSettingsTests(SimpleTestCase):
    def test_detail_view_settings_accept_multiple_layouts_and_find_default(self):
        settings = DetailViewSettings(
            layouts=[
                FieldLayout(
                    name="Compact",
                    is_default=False,
                    rows=[
                        LayoutRow(
                            columns=1,
                            items=[LayoutItem(id="name")],
                        )
                    ],
                ),
                FieldLayout(
                    name="Detailed",
                    rows=[
                        LayoutRow(
                            columns=1,
                            items=[LayoutItem(id="description")],
                        )
                    ],
                ),
            ]
        )

        self.assertEqual(
            [layout.name for layout in settings.layouts],
            ["Compact", "Detailed"],
        )
        self.assertEqual(settings.get_default_layout().name, "Detailed")

    def test_detail_view_settings_require_unique_layout_names_and_one_default(self):
        with self.assertRaisesRegex(ValidationError, "names must be unique"):
            DetailViewSettings(
                layouts=[
                    FieldLayout(name="Default"),
                    FieldLayout(name="Default", is_default=False),
                ]
            )

        with self.assertRaisesRegex(ValidationError, "Exactly one configured"):
            DetailViewSettings(
                layouts=[
                    FieldLayout(name="Compact", is_default=False),
                    FieldLayout(name="Detailed", is_default=False),
                ]
            )

        with self.assertRaisesRegex(ValidationError, "Exactly one configured"):
            DetailViewSettings(
                layouts=[
                    FieldLayout(name="Compact"),
                    FieldLayout(name="Detailed"),
                ]
            )

    def test_detail_view_settings_accept_named_tab_configurations(self):
        """
        Use case: A model declares multiple named detail-tab configurations.
        Expected result: Names, URL targets, folders, and ordering retain their payloads.
        """
        # 1. Define named layouts using literal URLs and a route name.
        settings = DetailViewSettings(
            tab_configurations=[
                DetailTabsConfiguration(
                    name=" Primary ",
                    tabs=[
                        DetailTab(
                            name=" Overview ",
                            url_name=" todos_detail_overview ",
                        ),
                        DetailTabFolder(
                            name="Related",
                            tabs=[
                                DetailTab(
                                    name="Initiative",
                                    url="/todos/{{pk}}/initiative/",
                                )
                            ],
                        ),
                    ],
                ),
                DetailTabsConfiguration(name="Empty", tabs=[]),
            ]
        )

        # 2. Confirm normalization and the easy-to-consume concrete models.
        primary = settings.tab_configurations[0]
        self.assertEqual(primary.name, "Primary")
        self.assertEqual(primary.tabs[0].name, "Overview")
        self.assertEqual(primary.tabs[0].url_name, "todos_detail_overview")
        self.assertIsInstance(primary.tabs[1], DetailTabFolder)
        self.assertEqual(primary.tabs[1].tabs[0].name, "Initiative")

        # 3. Confirm the API accepts several configurations and an empty default.
        self.assertEqual(settings.tab_configurations[1].name, "Empty")
        self.assertEqual(DetailViewSettings().tab_configurations, [])

    def test_detail_view_settings_reject_invalid_tab_configurations(self):
        """
        Use case: A model declares malformed default tabs or nested folders.
        Expected result: Configuration validation fails during application startup.
        """
        # 1. Reject unsupported URL templates.
        with self.assertRaisesRegex(ValidationError, "Only the.*pk.*placeholder"):
            DetailViewSettings(
                tab_configurations=[
                    DetailTabsConfiguration(
                        tabs=[DetailTab(name="Invalid", url="/todos/{{user_id}}/")]
                    )
                ]
            )

        # 2. Require exactly one literal URL or URL name for each tab.
        with self.assertRaisesRegex(ValidationError, "exactly one of url or url_name"):
            DetailTab(name="Missing target")
        with self.assertRaisesRegex(ValidationError, "exactly one of url or url_name"):
            DetailTab(name="Ambiguous", url="/todos/{{pk}}/", url_name="todos")

        # 3. Reject folders inside folders through the concrete child type.
        with self.assertRaises(ValidationError):
            DetailViewSettings(
                tab_configurations=[
                    DetailTabsConfiguration(
                        tabs=[
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
                ]
            )
