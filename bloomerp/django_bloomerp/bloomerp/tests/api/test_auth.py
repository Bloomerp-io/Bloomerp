from django.test import override_settings

from bloomerp.config.definition import BloomerpAuthSettings, BloomerpConfig, SessionAuthSettings
from bloomerp.tests.base import BaseBloomerpModelTestCase


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
