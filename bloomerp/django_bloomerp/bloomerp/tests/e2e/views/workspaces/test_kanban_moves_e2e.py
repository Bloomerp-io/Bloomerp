import re
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

from django.contrib.contenttypes.models import ContentType
from playwright.sync_api import Locator, Request, Response, Route, expect

from bloomerp.models import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig


class TestKanbanMovesE2E(BloomerpE2ETestCase):
    """Keep expanded lanes and active cards intact when moving through the real UI."""

    view_name = "workspace"
    auto_create_customers = False
    browser_context_options: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1280, "height": 720}
    }

    def create_fixtures(self) -> None:
        """Create two independently expandable lanes inside an embedded workspace board."""
        self.source_cards = [
            self.CustomerModel.objects.create(
                first_name=f"Source {index:02d}",
                last_name="Card",
                age=21 if index == 23 else 20,
            )
            for index in range(24)
        ]
        self.destination_cards = [
            self.CustomerModel.objects.create(
                first_name=f"Destination {index:02d}",
                last_name="Card",
                age=31 if index == 13 else 30,
            )
            for index in range(14)
        ]
        self.target_customer = self.source_cards[15]
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        age_field = ApplicationField.get_by_field(self.CustomerModel, "age")
        preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=content_type,
            name="Move regression",
            view_type="kanban",
            display_fields={"kanban": [age_field.pk]},
            options={
                "kanban": {
                    "group_by_field": "age",
                    "page_size": 10,
                    "sort_field": "first_name",
                    "sort_direction": "asc",
                    "custom_groupings": {"Young": ["20", "21"], "Older": ["30", "31"]},
                    "custom_group_order": ["Young", "Older"],
                    "lane_colouring": {
                        "Young": "#123456",
                        "Older": "#654321",
                        "31": "#abcdef",
                    },
                }
            },
        )
        tile = Tile.objects.create(
            name="Move regression",
            type="DATAVIEW_TILE",
            schema=DataViewTileConfig(
                content_type_id=content_type.pk,
                list_view_preference_id=preference.pk,
                actions=[],
            ).model_dump(mode="json"),
        )
        self.workspace = Workspace.objects.create(
            name="Move regression",
            user=self.admin_user,
            layout={
                "rows": [{"columns": 1, "items": [{"id": str(tile.pk), "colspan": 1}]}]
            },
        )

    def board(self) -> Locator:
        """Return the actual board component in the workspace."""
        return self.page.locator('[bloomerp-component="kanban-board"]')

    def lane(self, value: str) -> Locator:
        """Return one custom lane's card container."""
        return self.board().locator(
            f'.kanban-column[data-column-value="__group__:{value}"] .kanban-column-body'
        )

    def target_card(self) -> Locator:
        """Return the moved card independently of its current lane."""
        return self.board().locator(
            f'[bloomerp-component="kanban-card"][data-object-id="{self.target_customer.pk}"]'
        )

    def record_board_requests(self, request: Request) -> None:
        """Record unexpected complete-board GETs after the initial fixture has loaded."""
        if (
            request.method == "GET"
            and "/components/dataview/" in request.url
            and "/renderer-operation/" not in request.url
        ):
            self.board_reload_requests.append(request.url)

    def expect_column_response(self, loader: Locator) -> Any:
        """Wait for this lane's response rather than another lane using the same route."""
        expected_url = urlsplit(loader.get_attribute("hx-post"))
        expected_column = parse_qs(expected_url.query)["kanban_column"]

        def matches_column(response: Response) -> bool:
            """Match the requested lane and method on the shared column endpoint."""
            actual_url = urlsplit(response.url)
            return (
                response.request.method == "POST"
                and actual_url.path == expected_url.path
                and parse_qs(actual_url.query).get("kanban_column") == expected_column
            )

        return self.page.expect_response(matches_column)

    def load_expanded_source(self) -> None:
        """Expand the source through its real intersection loader before moving a later card."""
        expect(self.board()).to_have_attribute("data-component-initialized", "true")
        source = self.lane("Young")
        expect(source.locator('[bloomerp-component="kanban-card"]')).to_have_count(10)
        loader = source.locator("[data-kanban-column-loader]")
        with self.expect_column_response(loader) as response_info:
            loader.scroll_into_view_if_needed()
        self.assertEqual(response_info.value.status, 200, response_info.value.text())
        expect(source.locator('[bloomerp-component="kanban-card"]')).to_have_count(20)
        self.board_handle = self.board().element_handle()
        self.card_handle = self.target_card().element_handle()
        self.board_reload_requests: list[str] = []
        self.page.on("request", self.record_board_requests)

    def move_expanded_card(self) -> None:
        """Move a selected later-page card, preserving roots, focus, scroll and checkbox state."""
        card = self.target_card()
        self.board().focus()
        self.page.keyboard.press("ArrowDown")
        for _ in range(15):
            self.page.keyboard.press("ArrowDown")
        card.locator("[data-bulk-checkbox]").check()
        self.board().focus()
        destination = self.lane("Older")
        destination_scroll = destination.evaluate("element => element.scrollTop")
        move_url = self.board().get_attribute("data-kanban-move-url")
        self.page.keyboard.press("Alt+ArrowRight")
        expect(self.board()).to_have_class(re.compile(r"\bkanban-keyboard-moving\b"))
        with self.expect_response_for(move_url, method="POST"):
            self.page.keyboard.press("Enter")
        expect(card).not_to_have_attribute("data-kanban-moving", "true")
        self.assertGreaterEqual(
            destination.locator('[bloomerp-component="kanban-card"]').count(), 11
        )
        expect(
            self.lane("Young").locator('[bloomerp-component="kanban-card"]')
        ).to_have_count(19)
        self.assertTrue(self.board_handle.evaluate("element => element.isConnected"))
        self.assertTrue(self.card_handle.evaluate("element => element.isConnected"))
        expect(self.board()).to_be_focused()
        expect(card).to_have_class(re.compile(r"\bcell-focused\b"))
        expect(card.locator("[data-bulk-checkbox]")).to_be_checked()
        self.assertEqual(
            destination.evaluate("element => element.scrollTop"), destination_scroll
        )
        self.target_customer.refresh_from_db()
        self.assertEqual(self.target_customer.age, 30)
        self.assertIn("30", card.inner_text())
        self.assertEqual(self.board_reload_requests, [])

    def change_category_in_same_lane(self) -> None:
        """Change an existing card's category and colour without replacing its lane or root."""
        move_url = self.board().get_attribute("data-kanban-move-url")
        self.page.keyboard.press("Alt+ArrowLeft")
        self.page.keyboard.press("ArrowRight")
        self.page.keyboard.press("ArrowDown")
        with self.expect_response_for(move_url, method="POST"):
            self.page.keyboard.press("Enter")
        card = self.target_card()
        expect(card).not_to_have_attribute("data-kanban-moving", "true")
        expect(card.locator(".kanban-card-header")).to_have_css(
            "background-color", "rgb(171, 205, 239)"
        )
        expect(self.board()).to_be_focused()
        expect(card.locator("[data-bulk-checkbox]")).to_be_checked()
        self.target_customer.refresh_from_db()
        self.assertEqual(self.target_customer.age, 31)
        self.assertIn("31", card.inner_text())
        self.assertEqual(self.board_reload_requests, [])

    def finish_loading_lanes(self) -> None:
        """Expand both moved lanes to completion without omissions or duplicate cards."""
        for name, expected_count in [("Young", 23), ("Older", 15)]:
            lane = self.lane(name)
            loader = lane.locator("[data-kanban-column-loader]")
            if loader.count():
                loader.scroll_into_view_if_needed()
            expect(lane.locator('[bloomerp-component="kanban-card"]')).to_have_count(
                expected_count
            )
            expect(lane.locator("[data-kanban-column-loader]")).to_have_count(0)
            labels = lane.locator(".kanban-card-header").all_text_contents()
            self.assertEqual(labels, sorted(labels))
        ids = (
            self.board()
            .locator('[bloomerp-component="kanban-card"]')
            .evaluate_all("cards => cards.map(card => card.dataset.objectId)")
        )
        self.assertEqual(len(ids), 38)
        self.assertEqual(len(set(ids)), 38)
        self.assertEqual(self.board_reload_requests, [])

    def prepare_first_sorted_card(self) -> None:
        """Restore the source and give the moved card a name preceding both lanes."""
        self.target_customer.age = 20
        self.target_customer.first_name = "A incoming"
        self.target_customer.save(update_fields=["age", "first_name"])
        self.held_moves: list[Route] = []

    def hold_move(self, route: Route) -> None:
        """Delay the save until the source intersection loader has fetched its next page."""
        self.held_moves.append(route)

    def load_during_move_and_check_sort(self) -> None:
        """Load the source before a save commits, then preserve order without a board reload."""
        self.page.route("**/renderer-operation/move/**", self.hold_move)
        self.board().focus()
        self.page.keyboard.press("ArrowDown")
        self.page.keyboard.press("Alt+ArrowRight")
        self.page.keyboard.press("Enter")
        expect(self.target_card()).to_have_attribute("data-kanban-moving", "true")
        loader = self.lane("Young").locator("[data-kanban-column-loader]")
        with self.expect_column_response(loader) as response_info:
            loader.scroll_into_view_if_needed()
        response = response_info.value
        self.assertEqual(response.status, 200)
        submitted_ids = parse_qs(response.request.post_data)["kanban_loaded_ids"][
            0
        ].split(",")
        self.assertIn(str(self.target_customer.pk), submitted_ids)
        self.assertNotIn(f'data-object-id="{self.target_customer.pk}"', response.text())
        expect(
            self.lane("Young").locator('[bloomerp-component="kanban-card"]')
        ).to_have_count(23)
        self.target_customer.refresh_from_db()
        self.assertEqual(self.target_customer.age, 20)
        self.assertEqual(len(self.held_moves), 1)
        with self.expect_response_for(
            self.board().get_attribute("data-kanban-move-url"), method="POST"
        ):
            self.held_moves[0].continue_()
        self.page.unroute("**/renderer-operation/move/**", self.hold_move)
        expect(self.target_card()).not_to_have_attribute("data-kanban-moving", "true")
        expect(
            self.lane("Older").locator('[bloomerp-component="kanban-card"]').first
        ).to_have_attribute("data-object-id", str(self.target_customer.pk))
        self.assertTrue(self.card_handle.evaluate("element => element.isConnected"))
        self.assertTrue(self.board_handle.evaluate("element => element.isConnected"))
        self.assertEqual(self.board_reload_requests, [])

    def reset_target_card(self) -> None:
        """Restore the source category before the independent rejected-save scenario."""
        self.target_customer.age = 20
        self.target_customer.save(update_fields=["age"])

    def drag_expanded_card(self) -> None:
        """Drag a later-page card through native mouse events while retaining its active root."""
        card = self.target_card()
        card.scroll_into_view_if_needed()
        self.board().focus()
        source_box = card.locator(".kanban-card-header").bounding_box()
        self.assertIsNotNone(source_box)
        x = source_box["x"] + source_box["width"] / 2
        y = source_box["y"] + source_box["height"] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + 20, y + 5, steps=5)
        expect(self.board()).to_have_class(re.compile(r"\bkanban-moving\b"))
        target = self.lane("Older").locator(
            '[data-kanban-target][data-column-value="31"]'
        )
        target_box = target.bounding_box()
        self.assertIsNotNone(target_box)
        self.page.mouse.move(
            target_box["x"] + target_box["width"] / 2,
            max(20, min(700, target_box["y"] + target_box["height"] / 2)),
            steps=10,
        )
        with self.expect_response_for(
            self.board().get_attribute("data-kanban-move-url"), method="POST"
        ):
            self.page.mouse.up()
        expect(card).not_to_have_attribute("data-kanban-moving", "true")
        expect(
            self.lane("Older").locator(
                f'[data-object-id="{self.target_customer.pk}"][bloomerp-component="kanban-card"]'
            )
        ).to_have_count(1)
        expect(card).to_have_class(re.compile(r"\bcell-focused\b"))
        self.assertTrue(self.card_handle.evaluate("element => element.isConnected"))
        self.assertTrue(self.board_handle.evaluate("element => element.isConnected"))
        self.target_customer.refresh_from_db()
        self.assertEqual(self.target_customer.age, 31)
        self.assertEqual(self.board_reload_requests, [])

    def deny_move(self, route: Route) -> None:
        """Simulate the server rejecting a save to exercise the optimistic rollback path."""
        route.fulfill(status=403, content_type="text/plain", body="Permission denied")

    def reject_move_and_keep_state(self) -> None:
        """Reject a keyboard move and verify the expanded source and selection are restored."""
        self.page.route("**/renderer-operation/move/**", self.deny_move)
        card = self.target_card()
        self.board().focus()
        self.page.keyboard.press("ArrowDown")
        for _ in range(15):
            self.page.keyboard.press("ArrowDown")
        card.locator("[data-bulk-checkbox]").check()
        self.board().focus()
        move_url = self.board().get_attribute("data-kanban-move-url")
        self.page.keyboard.press("Alt+ArrowRight")
        expect(self.board()).to_have_class(re.compile(r"\bkanban-keyboard-moving\b"))
        with self.expect_response_for(move_url, method="POST"):
            self.page.keyboard.press("Enter")
        expect(card).not_to_have_attribute("data-kanban-moving", "true")
        expect(
            self.lane("Young").locator('[bloomerp-component="kanban-card"]')
        ).to_have_count(20)
        self.assertGreaterEqual(
            self.lane("Older").locator('[bloomerp-component="kanban-card"]').count(), 10
        )
        expect(card.locator("[data-bulk-checkbox]")).to_be_checked()
        expect(self.board()).to_be_focused()
        self.target_customer.refresh_from_db()
        self.assertEqual(self.target_customer.age, 20)
        self.assertEqual(self.board_reload_requests, [])

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Declare saved moves, same-lane edits, further expansion and rejected saves."""
        self.create_fixtures()
        return [
            E2ERequestScenario(
                name="Expanded boards keep state through keyboard moves and category changes",
                user=self.admin_user,
                url=self.workspace.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Load a later page of the source lane",
                        execute=self.load_expanded_source,
                    ),
                    E2EAction(
                        name="Move the selected later-page card",
                        execute=self.move_expanded_card,
                    ),
                    E2EAction(
                        name="Change category within its new lane",
                        execute=self.change_category_in_same_lane,
                    ),
                    E2EAction(
                        name="Continue expanding both lanes",
                        execute=self.finish_loading_lanes,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="A rejected move rolls back without resetting expanded lanes",
                prepare=self.reset_target_card,
                user=self.admin_user,
                url=self.workspace.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Expand the source lane", execute=self.load_expanded_source
                    ),
                    E2EAction(
                        name="Reject the card save",
                        execute=self.reject_move_and_keep_state,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Dragging a later-page card keeps the active card and board",
                prepare=self.reset_target_card,
                user=self.admin_user,
                url=self.workspace.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Expand the source lane", execute=self.load_expanded_source
                    ),
                    E2EAction(
                        name="Drag the expanded card to another lane",
                        execute=self.drag_expanded_card,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Source pagination during a pending move avoids duplicates and destination stays sorted",
                prepare=self.prepare_first_sorted_card,
                user=self.admin_user,
                url=self.workspace.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Expand the source lane", execute=self.load_expanded_source
                    ),
                    E2EAction(
                        name="Load while the move is pending",
                        execute=self.load_during_move_and_check_sort,
                    ),
                    E2EAction(
                        name="Verify both fully loaded lanes stay sorted",
                        execute=self.finish_loading_lanes,
                    ),
                ],
            ),
        ]
