from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from bloomerp.config.definition import (
    ApiKeyAuthSettings,
    BloomerpAuthSettings,
    BloomerpConfig,
    InteractiveAuthSettings,
    SessionAuthSettings,
)
from bloomerp.models.api_key import ApiKey
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.views.api.authentication import BloomerpApiKeyAuthentication


class TestBloomerpAuthApi(BaseBloomerpModelTestCase):
    def test_session_endpoint_reports_authentication_state(self):
        response = self.client.get("/api/auth/session/")
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"authenticated": False})

        self.client.force_login(self.normal_user)
        response = self.client.get("/api/auth/session/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["user"]["username"], "johndoe")
        self.assertEqual(payload["user"]["email"], "johndoe@example.com")

    @override_settings(
        MEDIA_URL="/media/",
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                session=SessionAuthSettings(user_fields=["id", "avatar"]),
            ),
        ),
    )
    def test_session_endpoint_serializes_file_fields_as_urls(self):
        self.normal_user.avatar = "avatars/profile.png"
        self.normal_user.save(update_fields=["avatar"])

        self.client.force_login(self.normal_user)
        response = self.client.get("/api/auth/session/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["user"]["avatar"], "/media/avatars/profile.png")

    def test_csrf_endpoint_returns_token_and_sets_cookie(self):
        response = self.client.get("/api/auth/csrf/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrfToken", response.json())
        self.assertIn("csrftoken", response.cookies)

    def test_login_and_logout_endpoints_manage_session(self):
        login_response = self.client.post(
            "/api/auth/login/",
            data={"username": "johndoe", "password": "testpass123"},
            content_type="application/json",
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.json()["authenticated"])

        session_response = self.client.get("/api/auth/session/")
        self.assertTrue(session_response.json()["authenticated"])

        logout_response = self.client.post("/api/auth/logout/")
        self.assertEqual(logout_response.status_code, 200)
        self.assertJSONEqual(logout_response.content, {"authenticated": False})

    def test_register_endpoint_is_disabled_by_default(self):
        response = self.client.post(
            "/api/auth/register/",
            data={"username": "janedoe", "email": "jane@example.com", "password": "testpass123"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Registration endpoints are disabled.")

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                session=SessionAuthSettings(enabled=False),
            ),
        )
    )
    def test_session_endpoints_can_be_disabled(self):
        response = self.client.get("/api/auth/session/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Session auth endpoints are disabled.")

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                session=SessionAuthSettings(login_identifier="email"),
            ),
        )
    )
    def test_login_can_use_email_identifier(self):
        response = self.client.post(
            "/api/auth/login/",
            data={"email": "johndoe@example.com", "password": "testpass123"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                interactive=InteractiveAuthSettings(
                    signup_enabled=True,
                ),
            ),
        )
    )
    def test_register_endpoint_can_create_and_login_user(self):
        response = self.client.post(
            "/api/auth/register/",
            data={
                "username": "janedoe",
                "email": "jane@example.com",
                "password": "testpass123",
                "first_name": "Jane",
                "last_name": "Doe",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["user"]["username"], "janedoe")
        self.assertEqual(payload["user"]["email"], "jane@example.com")

        session_response = self.client.get("/api/auth/session/")
        self.assertTrue(session_response.json()["authenticated"])

    @override_settings(
        AUTHENTICATION_BACKENDS=[
            "django.contrib.auth.backends.ModelBackend",
            "django.contrib.auth.backends.ModelBackend",
        ],
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                interactive=InteractiveAuthSettings(
                    signup_enabled=True,
                ),
            ),
        )
    )
    def test_register_endpoint_can_login_with_multiple_backends_configured(self):
        response = self.client.post(
            "/api/auth/register/",
            data={
                "username": "janedoe2",
                "email": "jane2@example.com",
                "password": "testpass123",
                "first_name": "Jane",
                "last_name": "Doe",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["authenticated"])
        session_response = self.client.get("/api/auth/session/")
        self.assertTrue(session_response.json()["authenticated"])

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                interactive=InteractiveAuthSettings(
                    signup_enabled=True,
                ),
            ),
        )
    )
    def test_register_endpoint_requires_all_user_creation_fields(self):
        response = self.client.post(
            "/api/auth/register/",
            data={"username": "janedoe", "password": "testpass123"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json()["detail"])

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                interactive=InteractiveAuthSettings(login_identifier="email"),
            ),
        )
    )
    def test_browser_login_can_use_email_identifier(self):
        response = self.client.post(
            "/login/",
            data={"username": "johndoe@example.com", "password": "testpass123"},
        )

        self.assertEqual(response.status_code, 302)
        session_response = self.client.get("/api/auth/session/")
        self.assertTrue(session_response.json()["authenticated"])


class TestBloomerpApiKeyAuthentication(BaseBloomerpModelTestCase):
    """
    This test suite tests whether token based authentication works
    """
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.authentication = BloomerpApiKeyAuthentication()

    def _create_api_key(self, **kwargs):
        api_key = ApiKey(
            account=kwargs.pop("account", self.normal_user),
            name=kwargs.pop("name", "Test key"),
            **kwargs,
        )
        raw_token = api_key.set_token()
        api_key.save()
        return api_key, raw_token

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                api_key=ApiKeyAuthSettings(enabled=True),
            ),
        )
    )
    def test_bearer_token_authenticates_as_linked_account(self):
        """
        Tests whether a bearer token authenticates as the linked account.
        """
        api_key, raw_token = self._create_api_key()
        request = self.factory.get(
            "/api/customers/",
            HTTP_AUTHORIZATION=f"Bearer {raw_token}",
        )

        user, auth = self.authentication.authenticate(request)

        self.assertEqual(user, self.normal_user)
        self.assertEqual(auth, api_key)
        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.last_used_at)

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                api_key=ApiKeyAuthSettings(enabled=True, header_name="X-API-Key"),
            ),
        )
    )
    def test_configured_api_key_header_authenticates_as_linked_account(self):
        api_key, raw_token = self._create_api_key()
        request = self.factory.get("/api/customers/", HTTP_X_API_KEY=raw_token)

        user, auth = self.authentication.authenticate(request)

        self.assertEqual(user, self.normal_user)
        self.assertEqual(auth, api_key)

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                api_key=ApiKeyAuthSettings(enabled=True),
            ),
        )
    )
    def test_invalid_api_key_fails_authentication(self):
        """
        Tests whether invalid key fails the auth
        """
        request = self.factory.get(
            "/api/customers/",
            HTTP_AUTHORIZATION="Bearer blp_live_missing_invalid",
        )

        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                api_key=ApiKeyAuthSettings(enabled=True),
            ),
        )
    )
    def test_revoked_api_key_fails_authentication(self):
        """Tests whether the revoke mechanism works
        """
        api_key, raw_token = self._create_api_key()
        api_key.revoke()
        request = self.factory.get(
            "/api/customers/",
            HTTP_AUTHORIZATION=f"Bearer {raw_token}",
        )

        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                api_key=ApiKeyAuthSettings(enabled=True),
            ),
        )
    )
    def test_expired_api_key_fails_authentication(self):
        api_key, raw_token = self._create_api_key(
            expires_at=timezone.now() - timezone.timedelta(days=1)
        )
        request = self.factory.get(
            "/api/customers/",
            HTTP_AUTHORIZATION=f"Bearer {raw_token}",
        )

        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

        api_key.refresh_from_db()
        self.assertIsNone(api_key.last_used_at)

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                api_key=ApiKeyAuthSettings(enabled=False),
            ),
        )
    )
    def test_disabled_api_key_authentication_ignores_token(self):
        _, raw_token = self._create_api_key()
        request = self.factory.get(
            "/api/customers/",
            HTTP_AUTHORIZATION=f"Bearer {raw_token}",
        )

        self.assertIsNone(self.authentication.authenticate(request))
