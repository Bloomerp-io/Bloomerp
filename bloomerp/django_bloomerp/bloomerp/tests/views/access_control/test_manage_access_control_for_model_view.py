import json

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from bloomerp.models.access_control.policy import Policy
from bloomerp.tests.base import BloomerpModelViewTestCase, RequestScenario
from bloomerp.views.access_control.manage_permissions import (
    CONTENT_TYPE_ID_KEY,
    GLOBAL_PERMISSIONS_KEY,
)


class TestManageAccessControlForModelView(BloomerpModelViewTestCase):
    """Tests class `ManageAccessControlForModelView` from `bloomerp/views/access_control/manage_permissions.py`."""

    view_name = "Create Policy"
    model = Policy

    def get_test_scenarios(self) -> list[RequestScenario]:
        # Add only the route scenarios this callable needs.
        return []

    def test_content_type_step_scopes_downstream_permissions(self):
        self.client.force_login(self.admin_user)
        endpoint = self.get_endpoint(self.view_name, None)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)

        response = self.client.post(endpoint, {"content_type": content_type.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["step_index"], 1)
        self.assertEqual(response.context["content_type_id"], content_type.pk)
        self.assertEqual(
            {permission.pk for permission in response.context["permissions"]},
            set(Permission.objects.filter(content_type=content_type).values_list("pk", flat=True)),
        )
        self.assertEqual(
            self.client.session["access_control_create_policy_wizard"][CONTENT_TYPE_ID_KEY],
            content_type.pk,
        )

    def test_changing_content_type_clears_model_specific_configuration(self):
        self.client.force_login(self.admin_user)
        endpoint = self.get_endpoint(self.view_name, None)
        first_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        second_content_type = ContentType.objects.get_for_model(Policy)
        self.client.post(endpoint, {"content_type": first_content_type.pk})

        session = self.client.session
        state = session["access_control_create_policy_wizard"]
        state[GLOBAL_PERMISSIONS_KEY] = ["view_customer"]
        state["__wizard_step"] = 0
        session["access_control_create_policy_wizard"] = state
        session.save()

        response = self.client.post(endpoint, {"content_type": second_content_type.pk})

        self.assertEqual(response.context["step_index"], 1)
        state = self.client.session["access_control_create_policy_wizard"]
        self.assertEqual(state[CONTENT_TYPE_ID_KEY], second_content_type.pk)
        self.assertIsNone(state[GLOBAL_PERMISSIONS_KEY])

    def test_selected_content_type_is_used_when_policy_is_created(self):
        self.client.force_login(self.admin_user)
        endpoint = self.get_endpoint(self.view_name, None)
        content_type = ContentType.objects.get_for_model(Policy)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="view_policy",
        )

        self.client.post(endpoint, {"content_type": content_type.pk})
        self.client.post(endpoint, {"global_permissions": [permission.codename]})
        self.client.post(
            endpoint,
            {
                "row_policy_name": "Policy rows",
                "row_policy_rules_json": "[]",
                "field_policy_name": "Policy fields",
                "field_policies_json": json.dumps(
                    {"__all__": [permission.codename]},
                ),
            },
        )

        response = self.client.post(
            endpoint,
            {
                "policy_name": "Manage policies",
                "policy_description": "Policy model access",
            },
        )

        self.assertEqual(response.status_code, 302)
        policy = Policy.objects.get(name="Manage policies")
        self.assertEqual(policy.row_policy.content_type, content_type)
        self.assertEqual(policy.field_policy.content_type, content_type)
