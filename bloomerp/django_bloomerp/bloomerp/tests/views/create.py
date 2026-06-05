import json

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from bloomerp.field_types import Lookup
from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
    UserCreateViewPreference,
    File,
)
from bloomerp.tests.views.crud_test_mixin import CrudViewTestMixin


class TestCreateView(CrudViewTestMixin):
    create_foreign_models = True
    auto_create_customers = False

    def extendedSetup(self):
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self._ensure_permissions_for_model(self.CustomerModel)
        self.fields_by_name = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
        }

    def get_url(self) -> str:
        return reverse("customers_add")

    def _ensure_permissions_for_model(self, model):
        content_type = ContentType.objects.get_for_model(model)
        for perm in model._meta.default_permissions:
            Permission.objects.get_or_create(
                codename=f"{perm}_{model._meta.model_name}",
                content_type=content_type,
                defaults={"name": f"Can {perm} {model._meta.verbose_name}"},
            )

    def grant_page_access(self, user):
        permission = Permission.objects.get(
            content_type=self.content_type,
            codename=f"add_{self.CustomerModel._meta.model_name}",
        )
        user.user_permissions.add(permission)
        user.refresh_from_db()
        return permission

    def group_row_rule(self, row_rule):
        if "conditions" in row_rule:
            return row_rule
        return {
            "connector": "OR",
            "conditions": [row_rule],
        }

    def grant_policy(self, *, user, field_names, row_rules=None):
        field_policy = FieldPolicy.objects.create(
            content_type=self.content_type,
            name=f"Field policy for {user.username}",
            rule={
                str(self.fields_by_name[field_name].pk): [f"add_{self.CustomerModel._meta.model_name}"]
                for field_name in field_names
            },
        )
        row_policy = RowPolicy.objects.create(
            content_type=self.content_type,
            name=f"Row policy for {user.username}",
        )
        for row_rule in row_rules or []:
            created_rule = RowPolicyRule.objects.create(
                row_policy=row_policy,
                rule=self.group_row_rule(row_rule),
            )
            created_rule.add_permission(f"add_{self.CustomerModel._meta.model_name}")

        policy = Policy.objects.create(
            name=f"Policy for {user.username}",
            description="Create view policy",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(user)
        page_permission = self.grant_page_access(user)
        policy.global_permissions.add(page_permission)
        return policy

    def test_GET_with_query_parameters_prefills_form(self):
        """
        This tests whether adding
        query parameters will prefill
        the form
        """
        self.client.force_login(self.admin_user)

        response = self.client.get(f"{self.get_url()}?first_name=XYZ")
        
        self.assertTrue(self.field_has_value(response, "first_name", "XYZ"))

    def test_get_renders_save_and_create_new_button_next_to_save(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="object-crud-container-save-button"', html=False)
        self.assertContains(response, 'id="object-crud-container-save-and-create-new-button"', html=False)
        self.assertContains(response, 'name="next"', html=False)
        self.assertContains(response, f'value="{self.get_url()}"', html=False)

    def test_post_with_next_creates_object_and_redirects_to_create_view(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(
            self.get_url(),
            {
                "first_name": "Another",
                "last_name": "Customer",
                "age": 30,
                "next": self.get_url(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.get_url())
        self.assertEqual(self.CustomerModel.objects.count(), 1)
        created = self.CustomerModel.objects.get()
        self.assertEqual(created.first_name, "Another")
        self.assertEqual(created.last_name, "Customer")

    def test_post_with_files_layout_field_attaches_uploaded_file_to_created_object(self):
        preference = UserCreateViewPreference.get_or_create_for_user(self.admin_user, self.content_type)
        preference.layout = {
            "rows": [
                {
                    "title": "Primary",
                    "columns": 2,
                    "items": [
                        {"id": self.fields_by_name["first_name"].pk, "colspan": 1},
                        {"id": self.fields_by_name["last_name"].pk, "colspan": 1},
                        {"id": self.fields_by_name["age"].pk, "colspan": 1},
                        {"id": self.fields_by_name["files"].pk, "colspan": 1},
                    ],
                }
            ]
        }
        preference.save(update_fields=["layout"])
        self.client.force_login(self.admin_user)

        uploaded_file = SimpleUploadedFile("timesheet.pdf", b"timesheet content", content_type="application/pdf")
        response = self.client.post(
            self.get_url(),
            {
                "first_name": "File",
                "last_name": "Owner",
                "age": 31,
                "files": uploaded_file,
            },
        )

        self.assertEqual(response.status_code, 302)
        created = self.CustomerModel.objects.get(first_name="File")
        attached_file = File.objects.get(name="timesheet.pdf")
        self.assertEqual(attached_file.content_type, self.content_type)
        self.assertEqual(attached_file.object_id, str(created.pk))
        self.assertTrue(attached_file.persisted)

    def test_get_without_add_permission_returns_403(self):
        """
        This tests whether the user can access the page without
        a global add permission
        """
        self.client.force_login(self.normal_user)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, 403)

    def test_get_blocks_when_required_fields_are_not_addable(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "do not have access to the required fields", html=False)
        self.assertContains(response, "disabled", html=False)

    def test_get_blocks_when_no_add_row_policy_exists(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[],
        )
        self.client.force_login(self.normal_user)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no create row policy applies", html=False)

    def test_get_renders_only_addable_fields_for_normal_user(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-layout-item-id="{self.fields_by_name["first_name"].pk}"', html=False)
        self.assertContains(response, f'data-layout-item-id="{self.fields_by_name["last_name"].pk}"', html=False)
        self.assertContains(response, f'data-layout-item-id="{self.fields_by_name["age"].pk}"', html=False)
        self.assertNotContains(response, f'data-layout-item-id="{self.fields_by_name["country"].pk}"', html=False)

    def test_post_shows_field_level_validation_error_in_layout(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.post(
            self.get_url(),
            {
                "first_name": "Allowed",
                "last_name": "Person",
                "age": "not-a-number",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-layout-item-id="{self.fields_by_name["age"].pk}"', html=False)
        self.assertContains(response, "border-red-500", html=False)

    def test_post_with_hidden_required_layout_field_shows_visible_error_message(self):
        self.normal_user.is_staff = True
        self.normal_user.save(update_fields=["is_staff"])
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        preference = UserCreateViewPreference.get_or_create_for_user(self.normal_user, self.content_type)
        preference.layout = {
            "rows": [
                {
                    "title": "Primary",
                    "columns": 2,
                    "items": [
                        {"id": self.fields_by_name["first_name"].pk, "colspan": 1},
                        {"id": self.fields_by_name["age"].pk, "colspan": 1},
                    ],
                }
            ]
        }
        preference.save(update_fields=["layout"])
        self.client.force_login(self.normal_user)

        response = self.client.post(
            self.get_url(),
            {
                "first_name": "Allowed",
                "age": "30",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Last name: This field is required.", html=False)
        self.assertEqual(self.CustomerModel.objects.count(), 0)

    def test_post_rejects_disallowed_injected_field(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.post(
            self.get_url(),
            {
                "first_name": "Allowed",
                "last_name": "Person",
                "age": 30,
                "country": self.CountryModel.objects.get(name="Belgium").pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Permission denied for fields: country", html=False)
        self.assertEqual(self.CustomerModel.objects.count(), 0)

    def test_post_rejects_values_that_do_not_match_add_row_policy(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.post(
            self.get_url(),
            {
                "first_name": "Blocked",
                "last_name": "Person",
                "age": 30,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "do not have permission to create an object with these values", html=False)
        self.assertEqual(self.CustomerModel.objects.count(), 0)

    def test_post_creates_object_when_permissions_and_row_rule_match(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.post(
            self.get_url(),
            {
                "first_name": "Allowed",
                "last_name": "Person",
                "age": 30,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.CustomerModel.objects.count(), 1)
        created = self.CustomerModel.objects.get()
        self.assertEqual(created.first_name, "Allowed")
        self.assertEqual(created.created_by, self.normal_user)

    def test_post_creates_object_when_and_row_rule_matches_foreign_key_value(self):
        self.normal_user.is_staff = True
        self.normal_user.save(update_fields=["is_staff"])
        belgium = self.CountryModel.objects.get(name="Belgium")
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age", "country"],
            row_rules=[
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "application_field_id": str(self.fields_by_name["last_name"].pk),
                            "operator": Lookup.EQUALS.value.id,
                            "value": "Peeters",
                        },
                        {
                            "application_field_id": str(self.fields_by_name["country"].pk),
                            "operator": Lookup.FOREIGN_EQUALS.value.id,
                            "value": str(belgium.pk),
                        },
                    ],
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.post(
            self.get_url(),
            {
                "first_name": "Jaimy",
                "last_name": "Peeters",
                "age": 30,
                "country": str(belgium.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.CustomerModel.objects.count(), 1)
        created = self.CustomerModel.objects.get()
        self.assertEqual(created.last_name, "Peeters")
        self.assertEqual(created.country, belgium)

    def test_component_post_from_foreign_field_widget_returns_trigger_instead_of_refresh(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(
            f'{reverse("components_create_object", kwargs={"content_type_id": self.content_type.pk})}?foreign_field_widget_id=widget-123',
            {
                "first_name": "Created",
                "last_name": "From Widget",
                "age": 30,
                "foreign_field_widget_id": "widget-123",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 204)
        self.assertNotIn("HX-Refresh", response)
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(
            trigger["bloomerp:foreign-field-object-created"]["foreign_field_widget_id"],
            "widget-123",
        )
        self.assertEqual(
            trigger["bloomerp:foreign-field-object-created"]["content_type_id"],
            self.content_type.pk,
        )
        self.assertEqual(
            trigger["bloomerp:foreign-field-object-created"]["object_label"],
            "Created From Widget",
        )

    def test_component_post_with_next_redirects_to_create_component(self):
        self.client.force_login(self.admin_user)
        component_url = reverse("components_create_object", kwargs={"content_type_id": self.content_type.pk})

        response = self.client.post(
            component_url,
            {
                "first_name": "Modal",
                "last_name": "Customer",
                "age": 30,
                "next": component_url,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], component_url)
        self.assertNotIn("HX-Refresh", response)
        self.assertEqual(self.CustomerModel.objects.count(), 1)

    def test_create_layout_preference_save_persists_shape(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)
        field = self.fields_by_name["first_name"]

        response = self.client.post(
            "/components/workspaces/create_layout_preference/",
            data=json.dumps(
                {
                    "content_type_id": self.content_type.pk,
                    "layout": {
                        "rows": [
                            {
                                "title": "Primary",
                                "columns": 3,
                                "items": [{"id": field.pk, "colspan": 2}],
                            }
                        ]
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        preference = UserCreateViewPreference.get_or_create_for_user(self.normal_user, self.content_type)
        self.assertEqual(preference.layout_obj.rows[0].title, "Primary")
        self.assertEqual(preference.layout_obj.rows[0].items[0].id, str(field.pk))
        self.assertEqual(preference.layout_obj.rows[0].items[0].colspan, 2)

    def test_empty_create_layout_is_repaired_with_default_items(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        preference = UserCreateViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            layout={},
        )

        repaired = UserCreateViewPreference.get_or_create_for_user(self.normal_user, self.content_type)

        self.assertEqual(repaired.pk, preference.pk)
        self.assertTrue(any(row.items for row in repaired.layout_obj.rows))

    def test_selected_create_preference_unselects_previous_preference(self):
        first = UserCreateViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            layout={},
        )
        second = UserCreateViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            layout={},
            selected=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertFalse(first.selected)
        self.assertTrue(second.selected)

    def test_shared_layout_available_fields_route_returns_create_items(self):
        self.grant_policy(
            user=self.normal_user,
            field_names=["first_name", "last_name", "age"],
            row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
        )
        self.client.force_login(self.normal_user)

        response = self.client.get(
            "/components/workspaces/create_layout_available_fields/",
            {
                "content_type_id": self.content_type.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.fields_by_name["first_name"].title)
        self.assertNotContains(response, self.fields_by_name["country"].title)
    
