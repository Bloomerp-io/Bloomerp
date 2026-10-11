"""Exercise independent workspace search without losing saved tile preferences."""

from collections.abc import Callable
from typing import Any, ClassVar

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from playwright.sync_api import Locator, expect

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig


class TestWorkspaceSearchPreferencesE2E(BloomerpE2ETestCase):
    """Preserve each tile's rendering and filters through actual search HTMX swaps."""

    view_name = "workspace"
    auto_create_customers = False
    browser_context_options: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1440, "height": 1000}
    }

    def create_fixtures(self) -> None:
        """Create contrasting preferences and two same-model tiles in the test DB."""
        self.customers = {
            name: self.CustomerModel.objects.create(
                first_name=name, last_name=last_name, age=age
            )
            for name, last_name, age in [
                ("Alpha", "Included", 30),
                ("Bravo", "Included", 30),
                ("Charlie", "Included", 40),
                ("Delta", "Hidden", 30),
            ]
        }
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        fields = {
            name: ApplicationField.get_by_field(self.CustomerModel, name).pk
            for name in ("first_name", "last_name", "age")
        }
        self.global_preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Global age table",
            selected=True,
            view_type="table",
            display_fields={"table": [fields["age"]]},
            options={"table": {"sort_field": "age", "sort_direction": "desc"}},
        )
        self.board_preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Tile age board",
            selected=False,
            view_type="kanban",
            display_fields={"kanban": [fields["last_name"]]},
            options={
                "kanban": {
                    "group_by_field": "age",
                    "page_size": 10,
                    "sort_field": "first_name",
                    "sort_direction": "desc",
                    "custom_groupings": {"Thirty": ["30"]},
                    "custom_group_order": ["Thirty"],
                    "lane_colouring": {"Thirty": "#123456"},
                }
            },
        )
        self.table_preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Tile names table",
            selected=False,
            view_type="table",
            display_fields={"table": [fields["first_name"], fields["last_name"]]},
            options={
                "table": {
                    "page_size": 10,
                    "sort_field": "first_name",
                    "sort_direction": "asc",
                }
            },
        )
        self.add_preference_default(self.board_preference, "age", 30)
        self.add_preference_default(self.table_preference, "last_name", "Included")
        self.board_tile = self.create_tile(
            self.board_preference, initial_query_params={"last_name": "Included"}
        )
        self.table_tile = self.create_tile(self.table_preference)
        self.workspace = Workspace.objects.create(
            name="Independent search tiles",
            user=self.admin_user,
            layout={
                "rows": [
                    {
                        "columns": 2,
                        "items": [
                            {"id": str(tile.pk), "colspan": 1}
                            for tile in (self.board_tile, self.table_tile)
                        ],
                    }
                ]
            },
        )
        self.original_preferences = self.preference_snapshot()

    def add_preference_default(
        self, preference: UserListViewPreference, field: str, value: str | int
    ) -> None:
        """Attach one saved default that must survive subsequent search requests."""
        saved_filter = SavedFilter.objects.create(
            name=f"{preference.name} default",
            scope="model",
            identifier=str(self.content_type.pk),
            filters=[
                Filter(
                    connector="AND",
                    conditions=[
                        FilterCondition(
                            field_path=field, lookup_id="equals", value=value
                        )
                    ],
                ).model_dump(mode="json")
            ],
        )
        preference.add_default_filter(saved_filter)

    def create_tile(
        self,
        preference: UserListViewPreference,
        initial_query_params: dict[str, object] | None = None,
    ) -> Tile:
        """Build one tile bound to an unselected preference and optional initial filters."""
        return Tile.objects.create(
            name=preference.name,
            type="DATAVIEW_TILE",
            schema=DataViewTileConfig(
                content_type_id=self.content_type.pk,
                list_view_preference_id=preference.pk,
                actions=[],
                initial_query_params=initial_query_params or {},
            ).model_dump(mode="json"),
        )

    def preference_snapshot(self) -> list[dict[str, Any]]:
        """Read persisted preference settings, including the globally selected identity."""
        return list(
            UserListViewPreference.objects.filter(
                user=self.admin_user, content_type=self.content_type
            )
            .order_by("pk")
            .values(
                "pk",
                "selected",
                "view_type",
                "display_fields",
                "options",
                "split_view_enabled",
            )
        )

    def tile(self, tile: Tile) -> Locator:
        """Resolve a tile after any component replacement without relying on duplicate IDs."""
        return self.page.locator(
            f'[bloomerp-component="workspace-tile"][data-layout-item-id="{tile.pk}"]'
        )

    def search(self, tile: Tile) -> Locator:
        """Resolve only the search box inside the chosen same-model tile."""
        return self.tile(tile).locator(
            f"#data-view-search-input-{self.content_type.pk}"
        )

    def assert_tiles(self, board_names: list[str], table_names: list[str]) -> None:
        """Check actual records, fields, lane styling and sorting in both independent tiles."""
        board = self.tile(self.board_tile)
        table = self.tile(self.table_tile)
        for tile in (board, table):
            expect(
                tile.locator('[bloomerp-component="dataview-container"]')
            ).to_have_attribute("data-component-initialized", "true")
        expect(board.locator('[bloomerp-component="kanban-board"]')).to_have_count(1)
        expect(board.locator('[bloomerp-component="datatable"]')).to_have_count(0)
        cards = board.locator('[bloomerp-component="kanban-card"]')
        expect(cards).to_have_count(len(board_names))
        self.assertEqual(
            cards.evaluate_all("cards => cards.map(card => card.dataset.objectId)"),
            [str(self.customers[name].pk) for name in board_names],
        )
        lane = board.locator('.kanban-column[data-column-value="__group__:Thirty"]')
        expect(lane).to_have_count(1)
        expect(lane.locator(".kanban-column-header")).to_have_css(
            "background-color", "rgb(18, 52, 86)"
        )
        for index in range(len(board_names)):
            card_fields = cards.nth(index).locator(".space-y-1 > div")
            expect(card_fields).to_have_count(1)
            expect(card_fields).to_contain_text("Last Name:")
            expect(card_fields).to_contain_text("Included")
        expect(table.locator('[bloomerp-component="datatable"]')).to_have_count(1)
        expect(table.locator('[bloomerp-component="kanban-board"]')).to_have_count(0)
        first_names = table.locator('tbody [data-application-field-name="first_name"]')
        expect(first_names).to_have_count(len(table_names))
        expect(first_names).to_have_text(table_names)
        expect(
            table.locator('tbody [data-application-field-name="last_name"]')
        ).to_have_count(len(table_names))
        expect(
            table.locator('tbody [data-application-field-name="age"]')
        ).to_have_count(0)
        expect(table.locator('th[aria-sort="ascending"]')).to_contain_text("First Name")
        self.assertEqual(self.preference_snapshot(), self.original_preferences)

    def assert_initial_tiles(self) -> None:
        """Verify saved defaults and initial filters produce contrasting initial views."""
        self.assert_tiles(["Bravo", "Alpha"], ["Alpha", "Bravo", "Charlie"])

    def search_action(
        self,
        tile: Tile,
        query: str,
        board_names: list[str],
        table_names: list[str],
        other_query: str,
    ) -> Callable[[], None]:
        """Create a deferred user search with request, rendered-state and isolation checks."""

        def execute() -> None:
            """Type or clear this tile's search and verify the complete resulting UI."""
            other_tile = (
                self.table_tile if tile.pk == self.board_tile.pk else self.board_tile
            )
            other_container = (
                self.tile(other_tile)
                .locator('[bloomerp-component="dataview-container"]')
                .element_handle()
            )
            self.assertIsNotNone(other_container)
            data_view_url = reverse(
                "components_dataview", kwargs={"content_type_id": self.content_type.pk}
            )
            with self.expect_response_for(data_view_url, method="GET") as response_info:
                self.search(tile).fill(query)
            self.assertEqual(response_info.value.status, 200)
            self.assert_tiles(board_names, table_names)
            expect(self.search(tile)).to_have_value(query)
            expect(self.search(other_tile)).to_have_value(other_query)
            self.assertTrue(other_container.evaluate("element => element.isConnected"))

        return execute

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Exercise search, replacement searches and clear independently on both tile types."""
        self.create_fixtures()
        return [
            E2ERequestScenario(
                name="Same-model workspace tiles preserve independent saved preferences during search",
                user=self.admin_user,
                url=self.workspace.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Load each tile's own preference and defaults",
                        execute=self.assert_initial_tiles,
                    ),
                    E2EAction(
                        name="Search Kanban without switching to the global table",
                        execute=self.search_action(
                            self.board_tile,
                            "Alpha",
                            ["Alpha"],
                            ["Alpha", "Bravo", "Charlie"],
                            "",
                        ),
                    ),
                    E2EAction(
                        name="Repeat Kanban search after its first response swap",
                        execute=self.search_action(
                            self.board_tile,
                            "Bravo",
                            ["Bravo"],
                            ["Alpha", "Bravo", "Charlie"],
                            "",
                        ),
                    ),
                    E2EAction(
                        name="Clear Kanban search while retaining default and initial filters",
                        execute=self.search_action(
                            self.board_tile,
                            "",
                            ["Bravo", "Alpha"],
                            ["Alpha", "Bravo", "Charlie"],
                            "",
                        ),
                    ),
                    E2EAction(
                        name="Leave a Kanban query active before searching the neighboring table",
                        execute=self.search_action(
                            self.board_tile,
                            "Bravo",
                            ["Bravo"],
                            ["Alpha", "Bravo", "Charlie"],
                            "",
                        ),
                    ),
                    E2EAction(
                        name="Search the table independently with its own columns and defaults",
                        execute=self.search_action(
                            self.table_tile, "Charlie", ["Bravo"], ["Charlie"], "Bravo"
                        ),
                    ),
                    E2EAction(
                        name="Repeat table search without changing the neighboring Kanban query",
                        execute=self.search_action(
                            self.table_tile, "Alpha", ["Bravo"], ["Alpha"], "Bravo"
                        ),
                    ),
                    E2EAction(
                        name="Clear the table search without clearing the Kanban search",
                        execute=self.search_action(
                            self.table_tile,
                            "",
                            ["Bravo"],
                            ["Alpha", "Bravo", "Charlie"],
                            "Bravo",
                        ),
                    ),
                    E2EAction(
                        name="Clear the remaining Kanban query and restore both configured views",
                        execute=self.search_action(
                            self.board_tile,
                            "",
                            ["Bravo", "Alpha"],
                            ["Alpha", "Bravo", "Charlie"],
                            "",
                        ),
                    ),
                    self.page_refresh(validators=self.assert_initial_tiles),
                ],
            )
        ]
