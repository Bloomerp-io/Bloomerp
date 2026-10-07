import json
from typing import Any
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.test.utils import CaptureQueriesContext

from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.models.definition import BloomerpModelConfig, ObjectAction
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestKanbanCardMoves(BloomerpComponentTestCase):
    """Exercise the card fragment and pagination contracts at the routed boundary."""

    view_name = "components_dataview_renderer_operation"
    auto_create_customers = False

    def create_fixtures(self) -> None:
        """Create two paginated lanes and a preference with visible fields and colours."""
        self.cards = [
            self.CustomerModel.objects.create(
                first_name=f"Card {index}", last_name="Example", age=age
            )
            for index, age in enumerate([20, 20, 20, 30, 30])
        ]
        self.age_field = ApplicationField.get_by_field(self.CustomerModel, "age")
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.preference = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Card response regression",
            view_type="kanban",
            display_fields={"kanban": [self.age_field.pk]},
            options={
                "kanban": {
                    "group_by_field": "age",
                    "page_size": 10,
                    "sort_field": "first_name",
                    "sort_direction": "asc",
                    "custom_groupings": {"Young": ["20", "21"], "Older": ["30"]},
                    "lane_colouring": {
                        "Young": "#123456",
                        "21": "#abcdef",
                        "Older": "#654321",
                    },
                }
            },
        )

    def route_kwargs(self, action: str) -> dict[str, Any]:
        """Resolve an operation against the fixture's preference."""
        return {
            "content_type_id": self.content_type.pk,
            "preference_id": self.preference.pk,
            "action": action,
        }

    def validate_card_fragment(self, response: HttpResponse) -> bool:
        """Verify a saved move returns one freshly rendered card, without lanes or loaders."""
        data = response.json()
        html = data["card_html"]
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select('[bloomerp-component="kanban-card"]')
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["data-object-id"], str(self.cards[0].pk))
        self.assertEqual(cards[0]["data-kanban-row-index"], "7")
        self.cards[0].refresh_from_db()
        self.assertEqual(self.cards[0].age, 21)
        self.assertIn("#abcdef", str(soup.select_one(".kanban-card-header")))
        value = soup.select_one(f'[data-application-field-id="{self.age_field.pk}"]')
        self.assertIsNotNone(value)
        self.assertIn("21", value.get_text())
        self.assertNotIn("kanban-column", html)
        self.assertNotIn("data-kanban-column-loader", html)
        return data["status"] == "ok"

    def validate_filtered_move(self, response: HttpResponse) -> bool:
        """Verify a saved card that leaves the current filters is omitted from the response."""
        self.cards[0].refresh_from_db()
        self.assertEqual(self.cards[0].age, 30)
        return response.json() == {"status": "ok", "card_html": ""}

    def prepare_read_only_user(self, scenario: RequestScenario) -> None:
        """Grant viewing rows and fields while denying changes to the grouping field."""
        field_policy = FieldPolicy.objects.create(
            content_type=self.content_type,
            name="Read-only cards",
            rule={"__all__": ["view_customer"]},
        )
        row_policy = RowPolicy.objects.create(
            content_type=self.content_type, name="Visible cards"
        )
        row_rule = RowPolicyRule.objects.create(
            row_policy=row_policy, rule={"connector": "AND", "conditions": []}
        )
        row_rule.add_permission("view_customer")
        policy = Policy.objects.create(
            name="Read-only board", row_policy=row_policy, field_policy=field_policy
        )
        policy.global_permissions.add(
            Permission.objects.get(
                content_type=self.content_type, codename="view_customer"
            )
        )
        policy.assign_user(self.normal_user)
        self.preference.shared_with_users.add(self.normal_user)

    def prepare_outgoing_move(self, scenario: RequestScenario) -> None:
        """Move a previously loaded source card before requesting more source cards."""
        self.cards[0].age = 30
        self.cards[0].save(update_fields=["age"])
        scenario.query_params = {"kanban_column": "__group__:Young", "kanban_page": 3}
        scenario.data = {"kanban_loaded_ids": str(self.cards[1].pk)}

    def prepare_incoming_move(self, scenario: RequestScenario) -> None:
        """Insert a card before an already loaded destination card in the sorted queryset."""
        self.cards[0].age = 30
        self.cards[0].save(update_fields=["age"])
        scenario.query_params = {"kanban_column": "__group__:Older", "kanban_page": 2}
        scenario.data = {"kanban_loaded_ids": f"{self.cards[0].pk},{self.cards[3].pk}"}

    @staticmethod
    def empty_action(request: HttpRequest, object: Model) -> HttpResponse | None:
        """Provide a harmless action callable for inspecting loaded card buttons."""
        return None

    @staticmethod
    def hide_action(request: HttpRequest, object: Model) -> bool:
        """Represent an action that is unavailable for the current card."""
        return False

    def prepare_card_actions(self, scenario: RequestScenario) -> None:
        """Configure visible and unavailable actions before loading unseen cards."""
        config = BloomerpModelConfig(
            object_actions=[
                ObjectAction(
                    id="available_action",
                    label="Available action",
                    execution_func=self.empty_action,
                ),
                ObjectAction(
                    id="hidden_action",
                    label="Hidden action",
                    execution_func=self.empty_action,
                    should_render_func=self.hide_action,
                ),
            ]
        )
        self.enterContext(
            patch.object(self.CustomerModel, "bloomerp_config", config, create=True)
        )

    def validate_loaded_card_actions(self, response: HttpResponse) -> bool:
        """Verify each newly loaded card includes only its available action button."""
        soup = BeautifulSoup(response.content, "html.parser")
        cards = soup.select('[bloomerp-component="kanban-card"]')
        self.assertEqual(len(cards), 2)
        self.assertEqual(
            {card["data-object-id"] for card in cards},
            {str(self.cards[1].pk), str(self.cards[2].pk)},
        )
        for card in cards:
            buttons = card.select("button[hx-post]")
            self.assertEqual(len(buttons), 1)
            self.assertEqual(buttons[0].get_text(strip=True), "Available action")
            self.assertIn(card["data-object-id"], buttons[0]["hx-post"])
            self.assertIn("available_action", buttons[0]["hx-post"])
        return "Hidden action" not in response.content.decode()

    def validate_ascending_order(self, response: HttpResponse) -> bool:
        """Place an alphabetically first incoming card before the loaded destination cards."""
        return response.json()["ordered_ids"] == [
            str(self.cards[index].pk) for index in [0, 3, 4]
        ]

    def capture_move_queries(self, scenario: RequestScenario) -> None:
        """Record request queries to guard against counting every board row during a save."""
        self.move_queries = self.enterContext(CaptureQueriesContext(connection))

    def validate_move_without_board_count(self, response: HttpResponse) -> bool:
        """Verify saving a single card never requests the full filtered board total."""
        table = self.CustomerModel._meta.db_table
        counts = [
            query["sql"]
            for query in self.move_queries
            if "COUNT(" in query["sql"].upper() and table in query["sql"]
        ]
        self.assertEqual(counts, [])
        return self.validate_ascending_order(response)

    def prepare_descending_order(self, scenario: RequestScenario) -> None:
        """Use descending names to verify ordering follows the saved preference."""
        self.preference.refresh_from_db()
        self.preference.options["kanban"]["sort_direction"] = "desc"
        self.preference.save(update_fields=["options"])

    def validate_descending_order(self, response: HttpResponse) -> bool:
        """Place the same incoming card after the descending destination cards."""
        return response.json()["ordered_ids"] == [
            str(self.cards[index].pk) for index in [4, 3, 0]
        ]

    def prepare_category_order(self, scenario: RequestScenario) -> None:
        """Sort by the grouping value to exercise same-lane category changes."""
        self.preference.refresh_from_db()
        self.preference.options["kanban"]["sort_field"] = "age"
        self.preference.save(update_fields=["options"])

    def validate_category_order(self, response: HttpResponse) -> bool:
        """Keep unchanged tied cards stable before a card whose sort value increased."""
        self.assertEqual(
            response.json()["ordered_ids"],
            [*sorted(str(card.pk) for card in self.cards[1:3]), str(self.cards[0].pk)],
        )
        return True

    def validate_page_order(self, response: HttpResponse) -> bool:
        """Order incoming and newly loaded cards together without re-rendering existing cards."""
        soup = BeautifulSoup(response.content, "html.parser")
        order = json.loads(
            soup.select_one("template[data-kanban-card-order] script").string
        )
        self.assertEqual(order, [str(self.cards[index].pk) for index in [0, 3, 4]])
        return f'data-object-id="{self.cards[0].pk}"' not in response.content.decode()

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Declare authoritative card rendering, access, validation and post-move loading cases."""
        self.create_fixtures()
        move_data = {
            "object_id": self.cards[0].pk,
            "group_value": "21",
            "row_index": "7",
        }
        return [
            RequestScenario(
                name="An incoming card receives ascending destination order",
                method="POST",
                user=self.admin_user,
                prepare=self.capture_move_queries,
                view_kwargs=self.route_kwargs("move"),
                data={
                    "object_id": self.cards[0].pk,
                    "group_value": "30",
                    "kanban_loaded_ids": f"{self.cards[3].pk},{self.cards[4].pk}",
                },
                expected=ExpectedResult(
                    response_validators=self.validate_move_without_board_count
                ),
            ),
            RequestScenario(
                name="An incoming card receives descending destination order",
                method="POST",
                user=self.admin_user,
                prepare=self.prepare_descending_order,
                view_kwargs=self.route_kwargs("move"),
                data={
                    "object_id": self.cards[0].pk,
                    "group_value": "30",
                    "kanban_loaded_ids": f"{self.cards[3].pk},{self.cards[4].pk}",
                },
                expected=ExpectedResult(
                    response_validators=self.validate_descending_order
                ),
            ),
            RequestScenario(
                name="A category change reorders cards inside a custom lane",
                method="POST",
                user=self.admin_user,
                prepare=self.prepare_category_order,
                view_kwargs=self.route_kwargs("move"),
                data={
                    **move_data,
                    "kanban_loaded_ids": ",".join(
                        str(card.pk) for card in self.cards[:3]
                    ),
                },
                expected=ExpectedResult(
                    response_validators=self.validate_category_order
                ),
            ),
            RequestScenario(
                name="Newly loaded cards retain available object action buttons",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("column"),
                query_params={"kanban_column": "__group__:Young", "kanban_page": 2},
                data={"kanban_loaded_ids": str(self.cards[0].pk)},
                prepare=self.prepare_card_actions,
                expected=ExpectedResult(
                    response_validators=self.validate_loaded_card_actions
                ),
            ),
            RequestScenario(
                name="A same-lane category move returns only the refreshed coloured card",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("move"),
                data=move_data,
                expected=ExpectedResult(
                    response_validators=self.validate_card_fragment
                ),
            ),
            RequestScenario(
                name="A move outside the active filter returns no card",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("move"),
                query_params={"age": 20},
                data={"object_id": self.cards[0].pk, "group_value": "30"},
                expected=ExpectedResult(
                    response_validators=self.validate_filtered_move
                ),
            ),
            RequestScenario(
                name="Read-only viewers cannot move a card",
                method="POST",
                user=self.normal_user,
                prepare=self.prepare_read_only_user,
                view_kwargs=self.route_kwargs("move"),
                data=move_data,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="A custom lane label is rejected as a concrete category value",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("move"),
                data={"object_id": self.cards[0].pk, "group_value": "Young"},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Moves require a POST request",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("move"),
                expected=ExpectedResult(status_code=405),
            ),
            RequestScenario(
                name="Source loading after a move does not skip its unseen card",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("column"),
                prepare=self.prepare_outgoing_move,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text(f'data-object-id="{self.cards[2].pk}"'),
                        self.does_not_contain_text(
                            f'data-object-id="{self.cards[1].pk}"'
                        ),
                        self.does_not_contain_text("data-kanban-column-loader"),
                    ]
                ),
            ),
            RequestScenario(
                name="Destination loading after a move excludes inserted and already loaded cards",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("column"),
                prepare=self.prepare_incoming_move,
                expected=ExpectedResult(
                    response_validators=[
                        self.validate_page_order,
                        self.contains_text(f'data-object-id="{self.cards[4].pk}"'),
                        self.does_not_contain_text(
                            f'data-object-id="{self.cards[0].pk}"'
                        ),
                        self.does_not_contain_text(
                            f'data-object-id="{self.cards[3].pk}"'
                        ),
                    ]
                ),
            ),
            RequestScenario(
                name="Malformed loaded IDs are rejected",
                user=self.admin_user,
                view_kwargs=self.route_kwargs("column"),
                query_params={
                    "kanban_column": "__group__:Young",
                    "kanban_loaded_ids": "invalid",
                },
                expected=ExpectedResult(status_code=400),
            ),
        ]
