import json

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from bloomerp.field_types import Lookup
from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.tests.views.crud_test_mixin import CrudViewTestMixin


class TestOverviewView(CrudViewTestMixin):
    create_foreign_models = True
    auto_create_customers = False

    def extendedSetup(self):
        self.customer = self.create_customer("Allowed", "Person", 30)
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self._ensure_permissions_for_model(self.CustomerModel)
        self.fields_by_name = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
        }

    def get_url(self):
        return reverse(
            "customers_detail_overview",
            kwargs={"pk": self.customer.pk},
        )

    def _ensure_permissions_for_model(self, model):
        content_type = ContentType.objects.get_for_model(model)
        for perm in model._meta.default_permissions:
            Permission.objects.get_or_create(
                codename=f"{perm}_{model._meta.model_name}",
                content_type=content_type,
                defaults={"name": f"Can {perm} {model._meta.verbose_name}"},
            )

    def grant_page_access(self, user, permission_name: str):
        permission = Permission.objects.get(
            content_type=self.content_type,
            codename=f"{permission_name}_{self.CustomerModel._meta.model_name}",
        )
        user.user_permissions.add(permission)
        user.refresh_from_db()
        return permission

    def grant_policy(
        self,
        *,
        user,
        view_field_names,
        change_field_names=None,
        view_row_rules=None,
        change_row_rules=None,
        include_global_view=True,
        include_global_change=True,
    ):
        field_rule = {
            str(self.fields_by_name[field_name].pk): [f"view_{self.CustomerModel._meta.model_name}"]
            for field_name in view_field_names
        }
        for field_name in change_field_names or []:
            field_rule.setdefault(str(self.fields_by_name[field_name].pk), []).append(
                f"change_{self.CustomerModel._meta.model_name}"
            )

        field_policy = FieldPolicy.objects.create(
            content_type=self.content_type,
            name=f"Field policy for {user.username}",
            rule=field_rule,
        )
        row_policy = RowPolicy.objects.create(
            content_type=self.content_type,
            name=f"Row policy for {user.username}",
        )
        for row_rule in view_row_rules or []:
            created_rule = RowPolicyRule.objects.create(
                row_policy=row_policy,
                rule=row_rule,
            )
            created_rule.add_permission(f"view_{self.CustomerModel._meta.model_name}")
        for row_rule in change_row_rules or []:
            created_rule = RowPolicyRule.objects.create(
                row_policy=row_policy,
                rule=row_rule,
            )
            created_rule.add_permission(f"change_{self.CustomerModel._meta.model_name}")

        policy = Policy.objects.create(
            name=f"Policy for {user.username}",
            description="Overview view policy",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(user)
        if include_global_view:
            policy.global_permissions.add(self.grant_page_access(user, "view"))
        if include_global_change:
            policy.global_permissions.add(self.grant_page_access(user, "change"))
        return policy

    def test_user_does_not_have_access_if_no_global_permission_to_object(self):
        self.grant_policy(
            user=self.normal_user,
            view_field_names=["first_name", "last_name", "age"],
            view_row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
            include_global_view=False,
            include_global_change=False,
        )
        self.client.force_login(self.normal_user)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, 403)

    def test_get_renders_only_viewable_fields(self):
        self.grant_policy(
            user=self.normal_user,
            view_field_names=["first_name", "last_name"],
            view_row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
            change_row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
            include_global_change=False,
        )
        self.client.force_login(self.normal_user)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-layout-item-id="{self.fields_by_name["first_name"].pk}"', html=False)
        self.assertContains(response, f'data-layout-item-id="{self.fields_by_name["last_name"].pk}"', html=False)
        self.assertNotContains(response, f'data-layout-item-id="{self.fields_by_name["age"].pk}"', html=False)

    def test_get_disables_view_only_fields(self):
        self.grant_policy(
            user=self.normal_user,
            view_field_names=["first_name", "age"],
            change_field_names=["first_name"],
            view_row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
            change_row_rules=[
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
        self.assertContains(response, 'name="age"', html=False)
        self.assertContains(response, "disabled", html=False)

    def test_POST_on_fields_user_has_no_access_to_gives_error_msg(self):
        self.grant_policy(
            user=self.normal_user,
            view_field_names=["first_name", "last_name", "age"],
            change_field_names=["first_name"],
            view_row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
            change_row_rules=[
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
                "age": 31,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Permission denied for fields: age", html=False)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.age, 30)

    def test_POST_on_field_with_error_should_give_error_message(self):
        self.grant_policy(
            user=self.normal_user,
            view_field_names=["first_name", "last_name", "age"],
            change_field_names=["age"],
            view_row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
            change_row_rules=[
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
                "age": "not-a-number",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-layout-item-id="{self.fields_by_name["age"].pk}"', html=False)
        self.assertContains(response, "border-red-500", html=False)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.age, 30)

    def test_post_updates_object_when_permissions_allow_change(self):
        self.grant_policy(
            user=self.normal_user,
            view_field_names=["first_name", "last_name", "age"],
            change_field_names=["first_name"],
            view_row_rules=[
                {
                    "application_field_id": str(self.fields_by_name["first_name"].pk),
                    "operator": Lookup.EQUALS.value.id,
                    "value": "Allowed",
                }
            ],
            change_row_rules=[
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
                "first_name": "Allowed Updated",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, "Allowed Updated")

    def test_detail_layout_preference_save_persists_shape(self):
        self.client.force_login(self.admin_user)
        field = self.fields_by_name["first_name"]

        response = self.client.post(
            "/components/workspaces/detail_layout_preference/",
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
        preference = UserDetailViewPreference.get_or_create_for_user(self.admin_user, self.content_type)
        self.assertEqual(preference.field_layout_obj.rows[0].title, "Primary")
        self.assertEqual(preference.field_layout_obj.rows[0].items[0].id, str(field.pk))
        self.assertEqual(preference.field_layout_obj.rows[0].items[0].colspan, 2)

    def test_shared_layout_available_fields_route_returns_detail_items(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(
            "/components/workspaces/detail_layout_available_fields/",
            {
                "content_type_id": self.content_type.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-layout-item-id", html=False)
