from typing import Any

from bs4 import BeautifulSoup
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
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
