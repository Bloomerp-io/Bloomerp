from typing import cast
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from playwright.sync_api import Request, expect

from bloomerp.form_behaviors.definition import (
    BehaviorAction,
    BehaviorConfig,
    FormBehavior,
)
from bloomerp.lookups import builtins as lookups
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.permissions.definition import (
    BloomerpPermission,
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.e2e.base import BaseE2ETestCase
from bloomerp.tests.e2e.generic.test_crud_mixin import TestCrudE2EMixin
from bloomerp.utils.models import get_detail_view_url


class TestOverviewViewE2E(TestCrudE2EMixin, BaseE2ETestCase):
    def extendedE2ESetup(self):
        pass

    def get_detail_view_url(self, instance: models.Model) -> str:
        return reverse(
            get_detail_view_url(model=type(instance)),
            kwargs={"pk": instance.pk},
        )    
    
    
    def goto_detail(self, instance: models.Model) -> None:
        self.goto(
            self.get_detail_view_url(instance)
        )

    def configure_todo_behavior(
        self,
        *,
        events: list[str],
        include_property: bool = False,
    ) -> Todo:
        """Create a Todo and install one title-listener behavior in its layout."""
        todo = Todo.objects.create(
            title="Behavior test todo",
            requested_by=self.admin_user,
        )
        content_type = ContentType.objects.get_for_model(Todo)
        fields = ApplicationField.get_for_model(Todo)
        listener = fields.get(field="title")
        items = [
            LayoutItem(
                id=listener.pk,
                config={
                    "behaviors": BehaviorConfig(
                        behaviors=[
                            FormBehavior(
                                id="title-message",
                                events=events,
                                actions=[
                                    BehaviorAction(
                                        action="show_message",
                                        config={
                                            "type": "info",
                                            "message": "Title behavior ran.",
                                        },
                                    )
                                ],
                            )
                        ]
                    ).to_storage()
                },
            ),
            LayoutItem(id=fields.get(field="status").pk),
        ]
        if include_property:
            items.append(LayoutItem(id=fields.get(field="is_completed").pk))
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={"content_type_id": content_type.pk},
        )
        self.assertIsInstance(preference, UserObjectLayoutPreference)
        preference = cast(UserObjectLayoutPreference, preference)
        preference.layout = FieldLayout(
            rows=[LayoutRow(columns=len(items), items=items)]
        ).model_dump(mode="json")
        preference.save(update_fields=["layout"])
        return todo

    def capture_behavior_requests(self) -> list[dict[str, object]]:
        """Collect behavior execution payloads emitted by the current page."""
        payloads: list[dict[str, object]] = []
        expected_path = urlsplit(
            self.url(reverse("components_form_behavior_execute"))
        ).path

        def capture(request: Request) -> None:
            """Record one JSON behavior request while ignoring unrelated traffic."""
            if request.method != "POST" or urlsplit(request.url).path != expected_path:
                return
            payload = request.post_data_json
            if isinstance(payload, dict):
                payloads.append(payload)

        self.page.on("request", capture)
        return payloads

    def authenticate_admin_browser(self) -> None:
        """Authenticate the browser with Django's test session cookie."""
        self.client.force_login(self.admin_user)
        session_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie.value,
                    "url": self.live_server_url,
                }
            ]
        )
    
    
    # ------------------------------
    # Test cases
    # ------------------------------
    # ------------------------------
    # Access Control
    # ------------------------------
    def test_normal_user_can_only_access_fields_according_to_permission(self):
        """
        UC: A normal user wants to access certain fields for an object.
        
        Expected Result: user can only access fields he is entitled to
        """
        #0. Create two objects
        todo1 = Todo.objects.create(
            title="Test Todo 1",
            requested_by=self.normal_user,
        )
        todo2 = Todo.objects.create(
            title="Test Todo 2",
            requested_by=self.normal_user,
        )
        todo3 = Todo.objects.create(
            title="Test Todo 3",
            requested_by=self.normal_user,
        )
        
        
        #1. Create two policies
        PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title" : [BloomerpPermission.VIEW],
                "requested_by" : [BloomerpPermission.VIEW],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="Test Todo 1"
                        )
                    ]
                )
            ]
        ).assign_user(self.normal_user)
        
        PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title" : [BloomerpPermission.VIEW],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="Test Todo 2"
                        )
                    ]
                )
            ]
        ).assign_user(self.normal_user)
        
        PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title" : [BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="OR",
                    permissions=[BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="Test Todo 3"
                        ),
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="Test Todo 3 - Updated"
                        )
                    ]
                )
            ]
        ).assign_user(self.normal_user)
        
        #2. Log in and navigate to the overview page
        self.login_as_normal_user()
        self.goto_detail(todo1)
        
        # 3. Assert that the user can only see the fields he is entitled to
        expect(
            self.locate_field("title")
        ).to_be_visible()
        expect(
            self.locate_field("requested_by")
        ).to_be_visible()
        expect(
            self.locate_field("status")
        ).not_to_be_visible()
        
        
        # 4. Navigate to the second object and assert that the user can only see the fields he is entitled to
        self.goto_detail(todo2)
        expect(
            self.locate_field("title")
        ).to_be_visible()
        expect(
            self.locate_field("requested_by")
        ).not_to_be_visible()
        expect(
            self.locate_field("status")
        ).not_to_be_visible()
        
        # 5. Navigate to the third object and assert that the user can only see the fields he is entitled to
        self.goto_detail(todo3)
        expect(
            self.locate_field("title")
        ).to_be_visible()
        expect(
            self.locate_field("requested_by")
        ).not_to_be_visible()
        
        self.locate_field("title").fill("Test Todo 3 - Unauthorized Update")
        
        with self.expect_response_for(
            self.get_detail_view_url(todo3),
            method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save").click()
        
        
        self.assertEqual(todo3.title, "Test Todo 3")
        
        self.locate_field("title").fill("Test Todo 3 - Updated")
        with self.expect_response_for(
            self.get_detail_view_url(todo3),
            method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save").click()
            
        todo3.refresh_from_db()
        
        self.assertEqual(todo3.title, "Test Todo 3 - Updated")
    
    
    def test_normal_user_can_not_crud_one_to_many_field_if_no_crud_access(self):
        """
        UC: A normal user should not be able to change a one-to-many field if they do not have create access to the related model
        
        Expected Result: The user should not be able to change the one-to-many field
        """
        # 1. Create a policy for the normal user that allows them to view the Todo model but not create new Todos
        PolicyManager.create_policy(
            model_or_content_type=Initiative,
            field_permissions={
                "__all__" : [BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="OR",
                    permissions=[BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
                    conditions=[RowPolicyRuleCondition(field="__all__")]
                )
            ]
        ).assign_user(self.normal_user)
        
        # 2. Create an initiative and a todo that is related to the initiative
        initiative = Initiative.objects.create(
            name="Test Initiative",
            description="Test Initiative Description",
        )
        todo = Todo.objects.create(
            title="Test Todo",
            initiative=initiative,
        )
        
        # 3. Log in as the normal user and navigate to the initiative detail view
        self.login_as_normal_user()
        self.goto_detail(initiative)
        
        NEW_NAME = "Test Initiative Updated"
        self.page.locator("#id_name").fill(NEW_NAME)
        
        # 4. Change the title of the initiative and click the save button. Assert that the title of the initiative has changed
        with self.expect_response_for(
            self.get_detail_view_url(initiative),
            method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save").click()
        
        # 5. Assert that the title of the initiative has changed
        initiative.refresh_from_db()
        self.assertEqual(initiative.name, NEW_NAME)
        
        # 6. Try to change the todo title and assert that the title has not changed
        NEW_TODO_NAME = "Test Todo Updated"
        self.page.locator("input[name=\"todos__0__title\"]").fill(NEW_TODO_NAME)
        with self.expect_response_for(
            self.get_detail_view_url(initiative),
            method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save").click()
        
        todo.refresh_from_db()
        self.assertEqual(todo.title, "Test Todo")
        
        
    def test_normal_user_can_crud_one_to_many_field_if_crud_access(self):
        """
        UC: A normal user should be able to change a one-to-many field if they have create access to the related model
        
        Expected Result: The user should be able to change the one-to-many field
        """
        # 1. Create a policy for the normal user that allows them to view and create new Todos
        PolicyManager.create_policy(
            model_or_content_type=Initiative,
            field_permissions={
                "__all__" : [BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="OR",
                    permissions=[BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
                    conditions=[RowPolicyRuleCondition(field="__all__")]
                )
            ]
        ).assign_user(self.normal_user)
        
        PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "__all__" : [BloomerpPermission.VIEW, BloomerpPermission.CHANGE, BloomerpPermission.ADD],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="OR",
                    permissions=[BloomerpPermission.VIEW, BloomerpPermission.CHANGE, BloomerpPermission.ADD],
                    conditions=[RowPolicyRuleCondition(field="__all__")]
                )
            ]
        ).assign_user(self.normal_user)
        
        # 2. Create an initiative and a todo that is related to the initiative
        initiative = Initiative.objects.create(
            name="Test Initiative",
            description="Test Initiative Description",
        )
        todo = Todo.objects.create(
            title="Test Todo",
            initiative=initiative,
        )
        
        # 3. Log in as the normal user and navigate to the initiative detail view
        self.login_as_normal_user()
        self.goto_detail(initiative)
        
        NEW_TODO_NAME = "Test Todo Updated"
        self.page.locator("input[name=\"todos__0__title\"]").fill(NEW_TODO_NAME)
        
        with self.expect_response_for(
            self.get_detail_view_url(initiative),
            method="POST"
        ) as response_info:
            self.page.get_by_role("button", name="Save").click()
            
        # 4. Assert that the title of the todo has changed
        todo.refresh_from_db()
        self.assertEqual(todo.title, NEW_TODO_NAME)
        
    # ------------------------------
    # Form behavior
    # ------------------------------

    def test_non_listener_change_does_not_execute_form_behaviors(self) -> None:
        """Changing a field without behaviors must not execute another listener."""
        todo = self.configure_todo_behavior(events=["change"])
        requests = self.capture_behavior_requests()
        self.authenticate_admin_browser()
        self.goto_detail(todo)

        self.locate_field("status").select_option("scoped")
        self.page.wait_for_timeout(300)

        self.assertEqual(requests, [])

    def test_initial_and_change_behavior_emits_one_request_per_event(self) -> None:
        """A dual-event listener emits one initial request and one changed request."""
        todo = self.configure_todo_behavior(events=["initial", "change"])
        requests = self.capture_behavior_requests()
        self.authenticate_admin_browser()
        execute_path = reverse("components_form_behavior_execute")

        with self.expect_response_for(execute_path, method="POST"):
            self.goto_detail(todo)
        self.page.wait_for_timeout(300)
        self.assertEqual(
            [request["event"] for request in requests],
            ["initial"],
        )

        with self.expect_response_for(execute_path, method="POST"):
            self.locate_field("title").fill("Changed once")
        self.page.wait_for_timeout(300)

        self.assertEqual(
            [request["event"] for request in requests],
            ["initial", "change"],
        )

    def test_unrelated_property_does_not_break_behavior_execution(self) -> None:
        """A rendered read-only property is ignored when another field listens."""
        todo = self.configure_todo_behavior(
            events=["change"],
            include_property=True,
        )
        self.authenticate_admin_browser()
        self.goto_detail(todo)

        with self.expect_response_for(
            reverse("components_form_behavior_execute"),
            method="POST",
        ) as response_info:
            self.locate_field("title").fill("Property-safe change")

        response = response_info.value
        self.assertEqual(response.status, 200)
        self.assertNotIn("error", response.json())
        
        
        
        
        
        
        
        
    
        
        
        
        
        
    

    
    
