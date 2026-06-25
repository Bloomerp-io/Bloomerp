from django.contrib.auth import authenticate
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from bloomerp.models import FieldPolicy, Policy, RowPolicy
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.models.users.user import User
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.utils.models import get_detail_view_url


class TestCreateUserView(BaseBloomerpModelTestCase):
    auto_create_customers = False

    def get_url(self) -> str:
        return reverse("users_add")

    def get_payload(self, username: str = "created-user") -> dict[str, str]:
        return {
            "username": username,
            "email": f"{username}@example.com",
            "password1": "exact-test-password-123",
            "password2": "exact-test-password-123",
        }

    def grant_user_create_policy(self, user: User) -> Policy:
        content_type = ContentType.objects.get_for_model(User)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="add_user",
        )
        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name=f"Create users row policy for {user.username}",
        )
        row_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "connector": "OR",
                "conditions": [
                    {
                        "application_field_id": "__all__",
                        "operator": "equals",
                        "value": "",
                    },
                ],
            },
        )
        row_rule.add_permission("add_user")
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name=f"Create users field policy for {user.username}",
            rule={"__all__": ["add_user"]},
        )
        policy = Policy.objects.create(
            name=f"Create users policy for {user.username}",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(user)
        policy.global_permissions.add(permission)
        return policy

    def test_user_is_created(self):
        # UC: A staff user with access creates a user with a password. Expected Result: The user can authenticate with the exact submitted password.
        # 1. Log in as the admin user and submit the create user form.
        self.client.force_login(self.admin_user)
        payload = self.get_payload()
        response = self.client.post(self.get_url(), payload)

        # 2. Confirm the user was created and the response redirects.
        self.assertEqual(response.status_code, 302)
        created_user = User.objects.get(username=payload["username"])
        self.assertEqual(created_user.email, payload["email"])

        # 3. Confirm the exact submitted password authenticates for the created user.
        authenticated_user = authenticate(
            username=payload["username"],
            password=payload["password1"],
        )
        self.assertEqual(authenticated_user, created_user)

    def test_view_redirects_user_to_correct_place(self):
        # UC: Creating a user succeeds. Expected Result: The response redirects to the created user's detail overview.
        # 1. Log in as the admin user and submit the create user form.
        self.client.force_login(self.admin_user)
        payload = self.get_payload("redirect-user")
        response = self.client.post(self.get_url(), payload)

        # 2. Confirm the redirect points at the created user's detail view.
        created_user = User.objects.get(username=payload["username"])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse(get_detail_view_url(User), kwargs={"pk": created_user.pk}),
        )

    def test_user_can_be_created_by_users_with_create_policy_for_user_model(self):
        # UC: A non-superuser staff member receives a create policy for users. Expected Result: They can create a user and authenticate with the submitted password.
        # 1. Grant the normal staff user create access to the User model.
        self.grant_user_create_policy(self.normal_user)
        self.client.force_login(self.normal_user)

        # 2. Submit the create user form as the policy-backed user.
        payload = self.get_payload("policy-created-user")
        response = self.client.post(self.get_url(), payload)

        # 3. Confirm the user is created and can authenticate with the submitted password.
        self.assertEqual(response.status_code, 302)
        created_user = User.objects.get(username=payload["username"])
        authenticated_user = authenticate(
            username=payload["username"],
            password=payload["password1"],
        )
        self.assertEqual(authenticated_user, created_user)

    def test_user_model_config_defines_default_layout(self):
        # UC: The User model is opened in a detail layout. Expected Result: The model config provides default user fields.
        # 1. Read the configured layout rows from the User model config.
        layout = User.bloomerp_config.layout
        layout_field_ids = [
            item.id
            for row in layout.rows
            for item in row.items
        ]

        # 2. Confirm expected identity and access fields are present.
        self.assertIn("username", layout_field_ids)
        self.assertIn("email", layout_field_ids)
        self.assertIn("is_active", layout_field_ids)
        self.assertIn("groups", layout_field_ids)
