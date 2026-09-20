from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from playwright.sync_api import expect

from bloomerp.lookups import builtins as lookups
from bloomerp.models import ApplicationField, FieldLayout, LayoutItem, LayoutRow
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
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.tests.views.crud_test_mixin import CrudViewTestMixin
from bloomerp.utils.models import get_create_view_url


class TestCreateViewE2E(CrudViewTestMixin, BloomerpE2ETestCase):
    create_foreign_models = True

    def goto_create_view(self, model: type[models.Model]) -> None:
        """Open the generated create view for a model."""
        self.goto(reverse(get_create_view_url(model=model)))

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Return browser scenarios for generated create views."""
        create_path = reverse(get_create_view_url(model=self.CountryModel))
        return [
            E2ERequestScenario(
                name="Admin resubmits an O2M row after a parent validation error",
                description=(
                    "A new inline child row must remain valid after an invalid "
                    "parent submission is corrected and submitted again."
                ),
                user=self.admin_user,
                url=create_path,
                prepare=self._prepare_country_o2m_layout,
                cleanup=self._cleanup_country_name_validator,
                actions=[
                    E2EAction(
                        name="Add a complete related customer row",
                        execute=self.custom_action(self._add_customer_row),
                    ),
                    E2EAction(
                        name="Submit a server-rejected country name",
                        execute=self.press_button_and_wait_for_response(
                            "Save",
                            create_path,
                            method="POST",
                            expected_status=200,
                        ),
                        validators=self._expect_invalid_form_preserves_o2m_row,
                    ),
                    E2EAction(
                        name="Correct the country name",
                        execute=self.input_field(
                            "name",
                            "Validation Recovery Country",
                        ),
                    ),
                    E2EAction(
                        name="Submit the corrected form",
                        execute=self.press_button_and_wait_for_response(
                            "Save",
                            create_path,
                            method="POST",
                            expected_status=302,
                        ),
                        validators=self._expect_country_and_customer_created,
                    ),
                ],
            )
        ]

    def _prepare_country_o2m_layout(self) -> None:
        """Expose editable customers, name, and planet fields in the create layout."""
        name_field = self.CountryModel._meta.get_field("name")
        if self._reject_first_submission_name not in name_field.validators:
            name_field.validators.append(self._reject_first_submission_name)
        country_fields = ApplicationField.get_for_model(self.CountryModel)
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserObjectLayoutPreference,
            scope={
                "content_type_id": ContentType.objects.get_for_model(
                    self.CountryModel
                ).pk
            },
        )
        preference.layout = FieldLayout(
            rows=[
                LayoutRow(
                    columns=1,
                    items=[
                        LayoutItem(
                            id=country_fields.get(field="customers").pk,
                            config={
                                "inline_fields": [
                                    "first_name",
                                    "last_name",
                                    "age",
                                    "customer_type",
                                ]
                            },
                        ),
                        LayoutItem(id=country_fields.get(field="name").pk),
                        LayoutItem(id=country_fields.get(field="planet").pk),
                    ],
                )
            ]
        ).model_dump()
        preference.save(update_fields=["layout"])

    def _cleanup_country_name_validator(self) -> None:
        """Remove the scenario-only server-side country name validator."""
        name_field = self.CountryModel._meta.get_field("name")
        if self._reject_first_submission_name in name_field.validators:
            name_field.validators.remove(self._reject_first_submission_name)

    @staticmethod
    def _reject_first_submission_name(value: str) -> None:
        """Reject the first scenario name without adding browser constraints."""
        if value == "Rejected Country":
            raise ValidationError("Choose a different country name.")

    def _add_customer_row(self) -> None:
        """Add a complete unsaved customer row and choose the parent planet."""
        widget = self.page.locator('[data-one-to-many-name="customers"]')
        widget.get_by_role("button", name="Add row").click()
        row = widget.locator("[data-one-to-many-row]").first
        row.locator('[data-one-to-many-cell="first_name"] input').fill("Grace")
        row.locator('[data-one-to-many-cell="last_name"] input').fill("Hopper")
        row.locator('[data-one-to-many-cell="age"] input').fill("36")

        customer_type_widget = row.locator(
            '[data-one-to-many-cell="customer_type"] '
            '[bloomerp-component="foreign-field-widget"]'
        )
        customer_type_widget.evaluate(
            "(element, value) => element.__bloomerp_component.setValue(value, true)",
            str(self.CustomerTypeModel.objects.get(name="Retail").pk),
        )

        planet_widget = self.page.locator(
            '[bloomerp-component="foreign-field-widget"][data-field-name="planet"]'
        )
        planet_widget.evaluate(
            "(element, value) => element.__bloomerp_component.setValue(value, true)",
            str(self.PlanetModel.objects.get(name="Earth").pk),
        )
        self.page.locator("#id_name").fill("Rejected Country")

    def _expect_invalid_form_preserves_o2m_row(self) -> None:
        """Assert the invalid response retains the complete related row."""
        expect(
            self.page.get_by_text("Choose a different country name.")
        ).to_be_visible()
        row = self.page.locator(
            '[data-one-to-many-name="customers"] [data-one-to-many-row]'
        ).first
        row_id = row.locator('input[name$="__id"]')
        expect(row_id).to_have_count(1)
        expect(row_id).to_have_value("")
        expect(row.locator('[data-one-to-many-cell="first_name"] input')).to_have_value(
            "Grace"
        )
        expect(row.locator('[data-one-to-many-cell="last_name"] input')).to_have_value(
            "Hopper"
        )
        expect(row.locator('[data-one-to-many-cell="age"] input')).to_have_value("36")
        expect(
            row.locator(
                '[data-one-to-many-cell="customer_type"] '
                'input[type="hidden"][data-generated="true"]'
            )
        ).to_have_value(str(self.CustomerTypeModel.objects.get(name="Retail").pk))

    def _expect_country_and_customer_created(self) -> None:
        """Assert the corrected parent and its retained child row were persisted."""
        country = self.CountryModel.objects.get(name="Validation Recovery Country")
        customer = country.customers.get(first_name="Grace")
        self.assertEqual(customer.last_name, "Hopper")
        self.assertEqual(customer.age, 36)
        self.assertEqual(customer.customer_type.name, "Retail")

    def test_admin_can_view_fields_with_initial_layout_in_create_view(self) -> None:
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
                field_locator = self.page.locator("#id_" + item.id)
                expect(field_locator).to_be_visible()

    def test_normal_user_can_only_view_fields_within_permission_scope(self) -> None:
        """
        UC: A normal user that has access to only some fields should be able to view only those fields in the create view

        Expected Result: The fields in the layout that the user has access to are visible to the user in the create view
        """
        # 1. Create a permission for the normal user
        policy = PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title": [BloomerpPermission.ADD],
                "content": [BloomerpPermission.VIEW],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.ADD],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="VALID TODO",
                        )
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)

        # 2. Login as normal user
        self.login_as_normal_user()

        # 3. Goto todo create
        self.goto_create_view(model=Todo)

        # 4. Check that the fields in the layout that the user has access to are visible
        for row in Todo.bloomerp_config.detail_view_settings.get_default_layout().rows:
            for item in row.items:
                field_locator = self.page.locator("#id_" + item.id)
                if item.id in [
                    "title",
                ]:
                    expect(field_locator).to_be_visible()
                else:
                    expect(field_locator).not_to_be_visible()

        # 5. Check that the labels are still visible for the fields that the user does not have access to
        for row in Todo.bloomerp_config.detail_view_settings.get_default_layout().rows:
            for item in row.items:
                field = ApplicationField.get_for_model(Todo).get(field=item.id)
                expect(self.page.get_by_text(field.title)).to_be_visible()

    def test_normal_user_can_only_create_objects_that_allign_with_row_policy(
        self,
    ) -> None:
        """
        UC: A normal user that has access to only some fields should be able to create objects that allign with the row policy

        Expected Result: The user can create objects that allign with the row policy
        """
        # 1. Create a permission for the normal user
        policy = PolicyManager.create_policy(
            model_or_content_type=Todo,
            field_permissions={
                "title": [BloomerpPermission.ADD],
                "content": [BloomerpPermission.VIEW],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.ADD],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="title",
                            operator=lookups.EQUALS.id,
                            value="VALID TODO",
                        )
                    ],
                )
            ],
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

    def test_normal_user_without_policy_gets_access_denied_message(self) -> None:
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

    def test_normal_user_with_policy_for_model_without_layout_gets_layout_of_visible_fields(
        self,
    ) -> None:
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
            row_permissions=[],
        )
        PolicyManager.assign(policy, self.normal_user)

        # 2. Login as normal user
        self.login_as_normal_user()

        # 3. Goto todo create
        self.goto_create_view(model=Todo)

        # 4. Check that the user gets a layout of the fields that they have access to
        for row in Todo.bloomerp_config.detail_view_settings.get_default_layout().rows:
            for item in row.items:
                field_locator = self.page.locator("#id_" + item.id)
                if item.id in [
                    "title",
                ]:
                    expect(field_locator).to_be_visible()
                else:
                    expect(field_locator).not_to_be_visible()
