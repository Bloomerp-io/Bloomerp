"""Check object context against the same configured API exposure used by tools."""

from unittest.mock import patch

from django.db.models import Model
from django.test import SimpleTestCase, override_settings

from bloomerp.agents.artifacts.object import OBJECT_ARTIFACT, ObjectArtifactPayload
from bloomerp.agents.definition import AIArtifactDescription
from bloomerp.config.definition import BloomerpConfig
from bloomerp.models import File
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.definition import ApiSettings, BloomerpModelConfig


@override_settings(BLOOMERP_CONFIG=BloomerpConfig())
class ObjectArtifactDescriptionTests(SimpleTestCase):
    """Describe live configuration without loading records or asserting user grants."""

    def describe_model(self, model: type[Model]) -> AIArtifactDescription:
        """Describe a reference whose object need not exist in the database."""
        return OBJECT_ARTIFACT.describe(
            ObjectArtifactPayload(
                model_label=model._meta.label,
                object_id="123",
                object_name="Referenced object",
            )
        )

    def assert_availability(
        self, description: AIArtifactDescription, *, enabled: bool
    ) -> None:
        """Check actionable availability wording without implying authorization."""
        expected = "available" if enabled else "unavailable"
        self.assertIn(
            f"Generated API retrieval and mutations are {expected} for this model.",
            description.summary,
        )
        if enabled:
            self.assertIn("Check api_assistant_mutation_catalog", description.summary)
            self.assertIn(
                "API availability does not grant user, row, or field permissions.",
                description.summary,
            )
        else:
            self.assertIn(
                "Do not use api_assistant_object_retrieve or api_assistant_mutations",
                description.summary,
            )

    def test_explicit_api_settings_override_global_availability(self) -> None:
        """Honor explicit enabled and disabled APIs independently of the global switch."""
        for global_enabled in (False, True):
            for model_enabled in (False, True):
                with (
                    self.subTest(
                        global_enabled=global_enabled, model_enabled=model_enabled
                    ),
                    override_settings(
                        BLOOMERP_CONFIG=BloomerpConfig(
                            auto_generate_api_endpoints=global_enabled
                        )
                    ),
                    patch.object(
                        File,
                        "bloomerp_config",
                        BloomerpModelConfig(
                            api_settings=ApiSettings(
                                enable_auto_generation=model_enabled
                            )
                        ),
                    ),
                ):
                    description = self.describe_model(File)
                    self.assert_availability(description, enabled=model_enabled)
                    self.assertEqual(
                        description.title, f"Referenced object | {File._meta.label}"
                    )
                    self.assertIn("record with id '123'", description.summary)

    def test_unspecified_api_settings_inherit_global_availability(self) -> None:
        """Recompute model availability from the current global fallback setting."""
        for enabled in (False, True):
            with (
                self.subTest(enabled=enabled),
                override_settings(
                    BLOOMERP_CONFIG=BloomerpConfig(auto_generate_api_endpoints=enabled)
                ),
                patch.object(
                    File, "bloomerp_config", BloomerpModelConfig(api_settings=None)
                ),
            ):
                self.assert_availability(self.describe_model(File), enabled=enabled)

    def test_email_account_configuration_disables_generated_api_tools(self) -> None:
        """Describe the actual disabled email-account configuration without name rules."""
        self.assert_availability(self.describe_model(EmailAccount), enabled=False)
        with patch.object(
            EmailAccount,
            "bloomerp_config",
            BloomerpModelConfig(api_settings=ApiSettings(enable_auto_generation=True)),
        ):
            self.assert_availability(self.describe_model(EmailAccount), enabled=True)

    def test_unconfigured_models_follow_generated_api_default(self) -> None:
        """Preserve generated API exposure for models without BloomerpModelConfig."""
        with (
            override_settings(
                BLOOMERP_CONFIG=BloomerpConfig(auto_generate_api_endpoints=False)
            ),
            patch.object(File, "bloomerp_config", None),
        ):
            self.assert_availability(self.describe_model(File), enabled=True)

    def test_abstract_and_proxy_models_remain_unavailable(self) -> None:
        """Respect generated API model restrictions even with explicit generation enabled."""
        with patch.object(
            File,
            "bloomerp_config",
            BloomerpModelConfig(api_settings=ApiSettings(enable_auto_generation=True)),
        ):
            for restriction in ("abstract", "proxy"):
                with self.subTest(restriction=restriction), patch.object(
                    File._meta, restriction, True
                ):
                    self.assert_availability(self.describe_model(File), enabled=False)

    def test_unknown_model_has_no_generated_api(self) -> None:
        """Keep stale references descriptive without advertising unavailable tools."""
        description = OBJECT_ARTIFACT.describe(
            ObjectArtifactPayload(
                model_label="removed.Missing",
                object_id="123",
                object_name="Removed object",
            )
        )
        self.assert_availability(description, enabled=False)
