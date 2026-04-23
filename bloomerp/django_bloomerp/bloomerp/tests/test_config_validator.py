from django.conf import settings
from django.test import SimpleTestCase, override_settings

from bloomerp.config.validator import BloomerpConfigurationValidator


class TestBloomerpConfigurationValidatorUserModel(SimpleTestCase):
    @override_settings(AUTH_USER_MODEL="bloomerp.User")
    def test_accepts_bloomerp_user_model(self):
        validator = BloomerpConfigurationValidator(settings=settings, models=[])

        responses = validator.validate_user_model()

        self.assertEqual(responses, [])

    @override_settings(AUTH_USER_MODEL="auth.User")
    def test_rejects_non_bloomerp_user_model(self):
        validator = BloomerpConfigurationValidator(settings=settings, models=[])

        responses = validator.validate_user_model()

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].code, "user_model.invalid_base_class")

    @override_settings(AUTH_USER_MODEL="missing.User")
    def test_rejects_unresolvable_user_model(self):
        validator = BloomerpConfigurationValidator(settings=settings, models=[])

        responses = validator.validate_user_model()

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].code, "user_model.invalid_auth_user_model")
