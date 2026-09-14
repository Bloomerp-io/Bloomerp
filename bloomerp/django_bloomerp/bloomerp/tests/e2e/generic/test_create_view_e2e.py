from django.urls import reverse
from playwright.sync_api import expect
from bloomerp.lookups import builtins as lookups
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager, UserPolicyManager
from bloomerp.tests.e2e.base import BaseE2ETestCase
from bloomerp.tests.views.crud_test_mixin import CrudViewTestMixin
from bloomerp.utils.models import get_create_view_url
from django.db import models

class TestCreateViewE2E(CrudViewTestMixin, BaseE2ETestCase):    
    def goto_create_view(self, model: models.Model):
        self.goto(
            reverse(get_create_view_url(model=model))
        )


    def test_admin_can_view_fields_with_initial_layout_in_create_view(self):
        """
        UC: An admin user that has access to all fields should be able to view all fields in the create view from the getgo

        Expected Result: The fields in the layout are visible to the admin user in the create view
        """
        self.login_as_admin()
        
        # 1. Goto todo create
        self.goto_create_view(model=Todo)
        
        # 2. Check that all fields in the layout are visible
        for row in Todo.bloomerp_config.detail_view_settings.get_default_layout().rows:
            for item in row.items:
                # Locate the field
                field_locator = self.page.locator("#id_"+item.id)
                expect(field_locator).to_be_visible()
                
    
    def test_normal_user_can_only_view_fields_within_permission_scope(self):
        """
        UC: A normal user that has access to only some fields should be able to view only those fields in the create view

        Expected Result: The fields in the layout that the user has access to are visible to the user in the create view
        """
        # 1. Create a permission for the normal user
        policy = PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title": [BloomerpPermission.ADD],
                "content" : [BloomerpPermission.VIEW],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.ADD],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="VALID TODO"
                        )
                    ]
                )
            ]
        )
        PolicyManager.assign(policy, self.normal_user)
        
        # 2. Login as normal user
        self.login_as_normal_user()
        
        # 3. Goto todo create
        self.goto_create_view(model=Todo)
        
        # 4. Check that the fields in the layout that the user has access to are visible
        for row in Todo.bloomerp_config.detail_view_settings.get_default_layout().rows:
            for item in row.items:
                field_locator = self.page.locator("#id_"+item.id)
                if item.id in ["title",]:
                    expect(field_locator).to_be_visible()
                else:
                    expect(field_locator).not_to_be_visible()
                    
        # 5. Check that the labels are still visible for the fields that the user does not have access to
        for row in Todo.bloomerp_config.detail_view_settings.get_default_layout().rows:
            for item in row.items:
                field = ApplicationField.get_for_model(Todo).get(
                    field=item.id
                )
                expect(self.page.get_by_text(field.title)).to_be_visible()
                
        
    def test_normal_user_can_only_create_objects_that_allign_with_row_policy(self):
        """
        UC: A normal user that has access to only some fields should be able to create objects that allign with the row policy

        Expected Result: The user can create objects that allign with the row policy
        """
        # 1. Create a permission for the normal user
        policy = PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title": [BloomerpPermission.ADD],
                "content" : [BloomerpPermission.VIEW],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.ADD],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="VALID TODO"
                        )
                    ]
                )
            ]
        )
        PolicyManager.assign(policy, self.normal_user)
        
        # 2. Login as normal user
        self.login_as_normal_user()
        
        # 3. Goto todo create
        self.goto_create_view(model=Todo)
        
        self.page.locator("#id_title").click()
        self.page.locator("#id_title").fill("Non valid")
        
        # 4. Try to save the object and check that the user gets a permission error
        save_button = self.page.get_by_role("button", name="Save", exact=True)
        create_path = reverse(get_create_view_url(model=Todo))

        with self.expect_response_for(create_path, method="POST") as response_info:
            save_button.click()
        self.assertEqual(response_info.value.status, 200)

        expect(self.page.get_by_text("You do not have permission to")).to_be_visible()

        # 5. Fill in a valid title and save the object
        self.page.locator("#id_title").fill("VALID TODO")

        with self.expect_response_for(create_path, method="POST") as response_info:
            save_button.click()
        self.assertEqual(response_info.value.status, 302)

        todo = Todo.objects.get(title="VALID TODO")
        self.assertIsNotNone(todo)
    
    
    def test_normal_user_without_policy_gets_access_denied_message(self):
        """
        UC: A normal user that has no access to the model should get an access denied message when trying to access the create view

        Expected Result: The user gets an access denied message
        """
        # 1. Login as normal user
        self.login_as_normal_user()
        
        # 2. Goto todo create
        self.goto_create_view(model=Todo)
        
        # 3. Check that the user gets an access denied message
        expect(self.page.get_by_text("Access denied")).to_be_visible()

    
    def test_normal_user_with_policy_for_model_without_layout_gets_layout_of_visible_fields(self):
        """
        UC: A normal user that has access to a model without a layout should get a layout of the fields that they have access to

        Expected Result: The user gets a layout of the fields that they have access to
        """
        # 1. Create a permission for the normal user
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={
                "title": [BloomerpPermission.ADD],
            },
            row_permissions=[]
        )
        PolicyManager.assign(policy, self.normal_user)
        
        # 2. Login as normal user
        self.login_as_normal_user()
        
        # 3. Goto todo create
        self.goto_create_view(model=Todo)
        
        # 4. Check that the user gets a layout of the fields that they have access to
        for row in Todo.bloomerp_config.detail_view_settings.get_default_layout().rows:
            for item in row.items:
                field_locator = self.page.locator("#id_"+item.id)
                if item.id in ["title",]:
                    expect(field_locator).to_be_visible()
                else:
                    expect(field_locator).not_to_be_visible()
