from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from bloomerp.config.definition import (
    ApiKeyAuthSettings,
    BloomerpAuthSettings,
    BloomerpConfig,
)
from bloomerp.models.api.api_key import ApiKey
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.api.authentication_classes import BloomerpApiKeyAuthentication


class TestBloomerpApiKeyAuthentication(BaseBloomerpTestCaseWithModels):
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
