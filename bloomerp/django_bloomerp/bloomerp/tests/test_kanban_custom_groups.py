from types import SimpleNamespace
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.test import RequestFactory

from bloomerp.dataviews.definition import DataviewState
from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.dataviews.kanban.renderer import KanbanDataviewRenderer
from bloomerp.models import ApplicationField
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestKanbanCustomGroups(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False
    create_foreign_models = True

    def create_cards(self) -> list[Any]:
        """Create integer lane values with deterministic card ordering."""
        country = self.CountryModel.objects.get(name="Belgium")
        return [
            self.CustomerModel.objects.create(
                first_name=f"Card {index}", last_name="Test", age=age, country=country
            )
            for index, age in enumerate([20, 30, 20, 40])
        ]

    def test_merged_lanes_paginate_and_keep_unmapped_values(self) -> None:
        """
        Use case: Numeric values share a coloured custom lane.
        Expected result: Counts and pagination cover members; unmapped cards remain visible.
        """
        # 1. Configure a lane spanning integer values and a stale colour.
        self.create_cards()
        field = ApplicationField.get_by_field(self.CustomerModel, "age")
        options = KanbanDataView(
            group_by_field="age",
            custom_groupings={"Young": ["20", "30"]},
            lane_colouring={"Young": "#123456", "40": "#abcdef", "Removed": "#ffffff"},
        )
        preference = SimpleNamespace(options={"kanban": {"sort_field": "first_name"}})
        # 2. Build both pages from the combined queryset.
        groups = KanbanDataviewRenderer.build_groups(
            self.CustomerModel.objects.all(),
            field,
            options=options,
            preference=preference,
            page_size=2,
        )
        next_groups = KanbanDataviewRenderer.build_groups(
            self.CustomerModel.objects.all(),
            field,
            options=options,
            preference=preference,
            page_size=2,
            page_number=2,
        )
        # 3. Verify counts, drop destinations, colours and page contents.
        self.assertEqual(
            [(group["label"], group["count"], group["colour"]) for group in groups],
            [("Young", 3, "#123456"), ("40", 1, "#abcdef")],
        )
        self.assertEqual(
            [item["value"] for item in groups[0]["destinations"]], ["20", "30"]
        )
        self.assertEqual(
            [item.first_name for item in groups[0]["items"]], ["Card 0", "Card 1"]
        )
        self.assertEqual(
            [item.first_name for item in next_groups[0]["items"]], ["Card 2"]
        )

    def test_foreign_key_custom_groups_keep_eligible_empty_members(self) -> None:
        """
        Use case: Related values are combined into a custom lane.
        Expected result: Empty eligible destinations remain available and stale members are ignored.
        """
        # 1. Configure two eligible countries and an obsolete member.
        self.create_cards()
        belgium = self.CountryModel.objects.get(name="Belgium")
        netherlands = self.CountryModel.objects.get(name="Netherlands")
        field = ApplicationField.get_by_field(self.CustomerModel, "country")
        options = KanbanDataView(
            custom_groupings={
                "Europe": [str(belgium.pk), str(netherlands.pk), "obsolete"]
            }
        )
        # 2. Build lanes with the related-object permission filter.
        groups = KanbanDataviewRenderer.build_groups(
            self.CustomerModel.objects.all(),
            field,
            user=self.admin_user,
            options=options,
        )
        # 3. Verify only eligible values contribute to the custom lane.
        self.assertEqual(groups[0]["label"], "Europe")
        self.assertEqual(groups[0]["count"], 4)
        self.assertEqual(
            [item["label"] for item in groups[0]["destinations"]],
            ["Belgium", "Netherlands"],
        )

    def test_removing_grouping_ignores_custom_lane_colours(self) -> None:
        """
        Use case: Custom grouping is removed while its colours remain saved.
        Expected result: Original value colours apply and stale custom colours are ignored.
        """
        # 1. Keep colours for an obsolete custom lane and an original value.
        self.create_cards()
        field = ApplicationField.get_by_field(self.CustomerModel, "age")
        options = KanbanDataView(lane_colouring={"Young": "#123456", "20": "#abcdef"})
        # 2. Build ordinary lanes.
        groups = KanbanDataviewRenderer.build_groups(
            self.CustomerModel.objects.all(), field, options=options
        )
        # 3. Verify active lane keys determine their colours.
        self.assertEqual([group["colour"] for group in groups], ["#abcdef", None, None])

    def test_move_uses_concrete_values_and_checks_permissions(self) -> None:
        """
        Use case: A card moves to another status within a merged lane.
        Expected result: The concrete integer is saved and unauthorized users cannot move cards.
        """
        # 1. Build a request and canonical state for a merged lane.
        card = self.create_cards()[0]
        field = ApplicationField.get_by_field(self.CustomerModel, "age")
        request = RequestFactory().post(
            "/", {"object_id": card.pk, "group_value": "30"}
        )
        request.user = self.admin_user
        state = DataviewState(
            request=request,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            model=self.CustomerModel,
            preference=SimpleNamespace(options={}),
            queryset=self.CustomerModel.objects.all(),
            fields=SimpleNamespace(accessible_fields=[(field, True)]),
            render_fields=[],
            avatar_field=None,
            options=KanbanDataView(
                group_by_field="age", custom_groupings={"Young": ["20", "30"]}
            ),
        )
        # 2. Save the concrete value, then attempt the move as a denied user.
        response = KanbanDataviewRenderer.handle_action("move", request, state)
        card.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(card.age, 30)
        request.user = self.normal_user
        self.assertEqual(
            KanbanDataviewRenderer.handle_action("move", request, state).status_code,
            403,
        )
        # 3. Reject a custom lane name as a model value.
        request.user = self.admin_user
        request.POST = request.POST.copy()
        request.POST["group_value"] = "Young"
        self.assertEqual(
            KanbanDataviewRenderer.handle_action("move", request, state).status_code,
            400,
        )

    def test_choice_groups_include_unused_status_destinations(self) -> None:
        """
        Use case: A custom lane combines populated and unused choice statuses.
        Expected result: Both choice destinations are available and other statuses retain lanes.
        """
        # 1. Create one card in the grouped choice field.
        Todo.objects.create(title="Grouped card", status="backlog")
        field = ApplicationField.get_by_field(Todo, "status")
        options = KanbanDataView(custom_groupings={"Planning": ["backlog", "scoped"]})
        # 2. Build grouped choice lanes.
        groups = KanbanDataviewRenderer.build_groups(
            Todo.objects.all(), field, options=options
        )
        # 3. Verify empty configured members and unmapped choice lanes remain available.
        self.assertEqual(groups[0]["count"], 1)
        self.assertEqual(
            [target["value"] for target in groups[0]["destinations"]],
            ["backlog", "scoped"],
        )
        self.assertIn("completed", [group["request_value"] for group in groups])

    def test_single_member_custom_lane_renders_concrete_drop_value(self) -> None:
        """
        Use case: A custom lane contains only one choice status.
        Expected result: Dropping into its body uses the status value, not its custom name.
        """
        # 1. Build a single-member choice lane with an actual card.
        Todo.objects.create(title="Single status card", status="backlog")
        field = ApplicationField.get_by_field(Todo, "status")
        options = KanbanDataView(custom_groupings={"Planning": ["backlog"]})
        groups = KanbanDataviewRenderer.build_groups(
            Todo.objects.all(), field, options=options
        )
        # 2. Render the board with the generated lane metadata.
        html = render_to_string(
            "cotton/features/dataviews/kanban.html",
            {
                "kanban_groups": groups,
                "content_type_id": ContentType.objects.get_for_model(Todo).pk,
                "preference": SimpleNamespace(pk=1, split_view_enabled=False),
                "fields": [],
            },
        )
        # 3. Verify the body uses a concrete model value without needing a selector.
        self.assertIn(
            'data-kanban-dropzone\n                data-column-value="backlog"', html
        )
        self.assertNotIn('data-column-value="__group__:Planning"\n            >', html)
        self.assertNotIn("data-kanban-destination", html)
        self.assertIn('data-kanban-target data-column-value="backlog"', html)

    def test_card_headers_use_member_colour_with_custom_lane_fallback(self) -> None:
        """
        Use case: A custom lane and one of its member statuses have colours.
        Expected result: Card headers use the member colour when present and the lane colour otherwise.
        """
        # 1. Create cards in each member of a custom lane.
        Todo.objects.create(title="Backlog card", status="backlog")
        Todo.objects.create(title="Scoped card", status="scoped")
        options = KanbanDataView(
            custom_groupings={"Planning": ["backlog", "scoped"]},
            lane_colouring={"Planning": "#123456", "scoped": "#eeeeee"},
        )
        # 2. Build the lane and inspect the card presentation metadata.
        groups = KanbanDataviewRenderer.build_groups(
            Todo.objects.all(),
            ApplicationField.get_by_field(Todo, "status"),
            options=options,
        )
        cards = {card.status: card for card in groups[0]["items"]}
        self.assertEqual(cards["backlog"].kanban_header_colour, "#123456")
        self.assertEqual(cards["backlog"].kanban_header_foreground, "#ffffff")
        self.assertEqual(cards["scoped"].kanban_header_colour, "#eeeeee")
        self.assertEqual(cards["scoped"].kanban_header_foreground, "#000000")
        # 3. Verify actual headers and movement categories receive these colours.
        html = render_to_string(
            "cotton/features/dataviews/kanban.html",
            {
                "kanban_groups": groups,
                "content_type_id": 27,
                "fields": [],
                "preference": SimpleNamespace(pk=1),
            },
        )
        self.assertIn("background-color: #123456; color: #ffffff", html)
        self.assertIn("background-color: #eeeeee; color: #000000", html)
        self.assertIn("--kanban-category-colour: #eeeeee", html)
