"""Exercise shipped tutorial defaults through the management command."""

from __future__ import annotations

from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar
from unittest.mock import patch

import yaml
from django.apps import apps
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bloomerp.models.tutorial import (
    Tutorial,
    TutorialProgress,
    TutorialRevision,
    TutorialTopic,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.utils.users import create_admin, create_normal_user

WELCOME = "bloomerp:welcome-to-bloomerp"
WORKFLOW = "bloomerp:notify-requester-on-todo-completion"
HELP = "django.contrib.auth:account-guide"


class TestTutorialSync(TestCase):
    """Check publication history and instance settings across releases."""

    audience_filter: ClassVar[list[dict[str, Any]]] = [
        {
            "connector": "AND",
            "conditions": [
                {"field_path": "username", "lookup_id": "equals", "value": "johndoe"}
            ],
        }
    ]

    @classmethod
    def setUpTestData(cls) -> None:
        """Build the metadata used by the real filter and export permission managers."""
        call_command("save_application_fields", suppress_output=True)
        cls.admin = create_admin()
        cls.learner = create_normal_user()

    def setUp(self) -> None:
        """Use a temporary tutorials directory for another installed Django app."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "tutorials"
        self.path.mkdir()
        patch_app_path = patch.object(
            apps.get_app_config("auth"), "path", directory.name
        )
        patch_app_path.start()
        self.addCleanup(patch_app_path.stop)

    def write_yaml(self, filename: str, value: dict[str, Any]) -> None:
        """Write a release definition to the temporary app package."""
        path = self.path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value), encoding="utf-8")

    def tutorial_document(self, key: str = "account-guide") -> dict[str, Any]:
        """Return a minimal portable tutorial with one auto-starting revision."""
        return {
            "schema_version": 1,
            "tutorial": {
                "source_key": key,
                "name": "Account guide",
                "available_to_all": True,
                "user_filter": deepcopy(self.audience_filter),
                "revisions": [
                    {
                        "number": 1,
                        "trigger_route": "bloomerp_home_view",
                        "auto_start": True,
                        "published_at": "2026-11-23T00:00:00+00:00",
                        "steps": [{"sequence": 1, "key": "welcome", "name": "Welcome"}],
                    }
                ],
            },
        }

    def sync(self) -> str:
        """Run the real command and return its reported counts."""
        stdout = StringIO()
        call_command("sync_defaults", "tutorials", stdout=stdout)
        return stdout.getvalue()

    def offers(self) -> dict[str, bool]:
        """Read the same eligibility and auto-start flags the learner receives."""
        self.client.force_login(self.learner)
        response = self.client.get(reverse("eligible_tutorials"))
        self.assertEqual(response.status_code, 200)
        return {
            tutorial["revision_id"]: tutorial["auto_start"]
            for tutorial in response.json()["tutorials"]
        }

    def test_first_install_and_identical_repeat_keep_identity_and_progress(
        self,
    ) -> None:
        """Install packaged tutorials and preserve their IDs and timestamps on repeat."""
        self.write_yaml("account.yaml", self.tutorial_document())
        self.assertIn("3 default tutorial(s)", self.sync())
        welcome = Tutorial.objects.get(source_key=WELCOME)
        self.assertEqual(welcome.revisions.get().steps.count(), 9)
        workflow = Tutorial.objects.get(source_key=WORKFLOW)
        self.assertEqual(workflow.topics.get().source_key, "bloomerp:getting-started")
        workflow_revision = workflow.revisions.get()
        self.assertIn(str(workflow_revision.pk), self.offers())
        setup_step = workflow_revision.steps.get(key="save-workflow")
        self.assertIn(
            "notify-on-completion",
            [highlight["id"] for highlight in setup_step.interaction["highlights"]],
        )
        tutorial = Tutorial.objects.get(source_key=HELP)
        revision = tutorial.revisions.get()
        step = revision.steps.get()
        record = TutorialProgress.objects.create(
            revision=revision,
            user=self.learner,
            completed_at=timezone.now(),
            current_step=step,
        )
        self.assertFalse(self.offers()[str(revision.pk)])
        self.sync()
        self.assertEqual(Tutorial.objects.get(source_key=HELP).pk, tutorial.pk)
        self.assertEqual(tutorial.revisions.get().pk, revision.pk)
        self.assertEqual(revision.steps.get().pk, step.pk)
        self.assertEqual(revision.progress_records.get().pk, record.pk)
        self.assertEqual(
            Tutorial.objects.get(pk=tutorial.pk).datetime_updated,
            tutorial.datetime_updated,
        )

    def test_new_revision_uses_revision_specific_progress(self) -> None:
        """Offer a new published number while keeping prior completed learner history."""
        document = self.tutorial_document()
        self.write_yaml("account.yaml", document)
        self.sync()
        first = TutorialRevision.objects.get(tutorial__source_key=HELP)
        record = TutorialProgress.objects.create(
            revision=first,
            user=self.learner,
            dismissed_at=timezone.now(),
        )
        second = deepcopy(document["tutorial"]["revisions"][0])
        second.update(number=2, published_at="2026-11-24T00:00:00+00:00")
        second["steps"][0]["name"] = "The new welcome"
        document["tutorial"]["revisions"].append(second)
        self.write_yaml("account.yaml", document)
        self.sync()
        latest = TutorialRevision.objects.get(tutorial__source_key=HELP, number=2)
        self.assertTrue(self.offers()[str(latest.pk)])
        self.assertNotIn(str(first.pk), self.offers())
        self.assertEqual(first.steps.get().name, "Welcome")
        self.assertTrue(
            TutorialProgress.objects.filter(pk=record.pk, revision=first).exists()
        )

    def test_retirement_and_restoration_respect_existing_flags_and_progress(
        self,
    ) -> None:
        """Retire only when declared and restore the same revision and learner record."""
        document = self.tutorial_document()
        self.write_yaml("account.yaml", document)
        self.sync()
        revision = TutorialRevision.objects.get(tutorial__source_key=HELP)
        progress = TutorialProgress.objects.create(
            revision=revision,
            user=self.learner,
            first_shown_at=timezone.now(),
        )
        (self.path / "account.yaml").unlink()
        self.sync()
        self.assertIn(str(revision.pk), self.offers())
        self.write_yaml("retired.yml", {"schema_version": 1, "retire": "account-guide"})
        self.sync()
        self.assertNotIn(str(revision.pk), self.offers())
        revision.tutorial.refresh_from_db()
        self.assertTrue(revision.tutorial.is_active)
        self.assertTrue(revision.tutorial.source_retired)

        (self.path / "retired.yml").unlink()
        self.write_yaml("moved/renamed.yaml", document)
        self.sync()
        self.assertFalse(self.offers()[str(revision.pk)])
        self.assertEqual(revision.progress_records.get().pk, progress.pk)
        self.assertFalse(Tutorial.objects.get(pk=revision.tutorial_id).source_retired)

    def test_topics_preserve_source_identity_local_topics_and_order(self) -> None:
        """Link shared and cross-app topics in sequence order across a rename."""
        topics = {
            "schema_version": 1,
            "topics": [
                {"source_key": "accounts", "name": "Accounts", "sequence": 20},
            ],
        }
        self.write_yaml("topics.yaml", topics)
        first = self.tutorial_document()
        first["tutorial"]["topics"] = ["accounts", "bloomerp:getting-started"]
        second = self.tutorial_document("profile-guide")
        second["tutorial"]["topics"] = ["accounts"]
        self.write_yaml("account.yaml", first)
        self.write_yaml("profile.yaml", second)
        self.sync()
        topic = TutorialTopic.objects.get(source_key="django.contrib.auth:accounts")
        tutorial = Tutorial.objects.get(source_key=HELP)
        self.assertEqual(
            list(tutorial.topics.values_list("source_key", flat=True)),
            ["bloomerp:getting-started", "django.contrib.auth:accounts"],
        )
        self.assertEqual(topic.tutorials.count(), 2)
        tutorial.topics.add(
            TutorialTopic.objects.create(name="Our internal setup", sequence=30)
        )
        topics["topics"][0].update(name="People and access", sequence=5)
        self.write_yaml("topics.yaml", topics)
        self.sync()
        self.assertEqual(
            TutorialTopic.objects.get(source_key=topic.source_key).pk, topic.pk
        )
        self.assertEqual(
            list(tutorial.topics.values_list("name", flat=True)),
            ["People and access", "Getting started", "Our internal setup"],
        )

    def test_local_settings_and_assignments_survive_later_defaults(self) -> None:
        """Keep local audience, enablement, and unrelated local tutorials."""
        document = self.tutorial_document()
        self.write_yaml("account.yaml", document)
        self.sync()
        tutorial = Tutorial.objects.get(source_key=HELP)
        self.assertEqual(tutorial.user_filter, self.audience_filter)
        tutorial.is_active = False
        tutorial.available_to_all = False
        tutorial.user_filter = [{"connector": "AND", "conditions": []}]
        tutorial.save()
        tutorial.assigned_users.add(self.learner)
        group = Group.objects.create(name="Local learners")
        tutorial.assigned_groups.add(group)
        local = Tutorial.objects.create(name="Local training")

        document["tutorial"].update(name="Renamed guide", user_filter=[])
        self.write_yaml("account.yaml", document)
        self.sync()
        tutorial.refresh_from_db()
        self.assertEqual(tutorial.name, "Renamed guide")
        self.assertFalse(tutorial.is_active)
        self.assertFalse(tutorial.available_to_all)
        self.assertEqual(tutorial.user_filter, [{"connector": "AND", "conditions": []}])
        self.assertEqual(tutorial.assigned_users.get(), self.learner)
        self.assertEqual(tutorial.assigned_groups.get(), group)
        self.assertTrue(Tutorial.objects.filter(pk=local.pk, source_key=None).exists())

    def test_invalid_definitions_are_rejected_before_any_default_writes(self) -> None:
        """Reject missing or malformed identities, duplicate keys, and missing topics."""
        for key, message in (
            (None, "source_key"),
            ("", "Invalid source key"),
            ("with spaces", "Invalid source key"),
            ("bloomerp:claimed", "Invalid source key"),
        ):
            with self.subTest(key=key):
                document = self.tutorial_document()
                document["tutorial"]["source_key"] = key
                self.write_yaml("invalid.yaml", document)
                with self.assertRaisesRegex(
                    CommandError,
                    f"django.contrib.auth/tutorials/invalid.yaml.*{message}"
                    if key is not None
                    else "django.contrib.auth/tutorials/invalid.yaml",
                ):
                    self.sync()
                self.assertFalse(Tutorial.objects.exists())
                self.assertFalse(TutorialTopic.objects.exists())

        document = self.tutorial_document()
        del document["tutorial"]["source_key"]
        self.write_yaml("invalid.yaml", document)
        with self.assertRaisesRegex(
            CommandError, "django.contrib.auth/tutorials/invalid.yaml"
        ):
            self.sync()
        document = self.tutorial_document()
        document["tutorial"]["topics"] = ["does-not-exist"]
        self.write_yaml("invalid.yaml", document)
        with self.assertRaisesRegex(CommandError, "Unknown tutorial topic"):
            self.sync()
        document["tutorial"]["topics"] = []
        self.write_yaml("invalid.yaml", document)
        self.write_yaml("z-duplicate.yaml", document)
        with self.assertRaisesRegex(
            CommandError, "z-duplicate.yaml.*Duplicate or conflicting"
        ):
            self.sync()
        self.assertFalse(Tutorial.objects.exists())
        self.assertFalse(TutorialTopic.objects.exists())

    def test_conflicting_published_content_rolls_back_the_release(self) -> None:
        """Reject a rewritten published revision before changing even other defaults."""
        document = self.tutorial_document()
        self.write_yaml("account.yaml", document)
        self.sync()
        document["tutorial"]["revisions"][0]["steps"][0]["name"] = "Rewritten snapshot"
        self.write_yaml("account.yaml", document)
        self.write_yaml(
            "topics.yaml",
            {
                "schema_version": 1,
                "topics": [{"source_key": "new", "name": "New topic"}],
            },
        )
        with self.assertRaisesRegex(CommandError, "account.yaml.*Revision 1 conflicts"):
            self.sync()
        self.assertFalse(
            TutorialTopic.objects.filter(source_key="django.contrib.auth:new").exists()
        )
        self.assertEqual(
            TutorialRevision.objects.get(tutorial__source_key=HELP).steps.get().name,
            "Welcome",
        )

    def test_portable_export_honors_the_topic_relation_and_key_visibility(self) -> None:
        """Keep readable content and omit local IDs and protected topic keys."""
        document = self.tutorial_document()
        document["tutorial"]["topics"] = ["bloomerp:getting-started", "private"]
        self.write_yaml("account.yaml", document)
        self.write_yaml(
            "topics.yaml",
            {
                "schema_version": 1,
                "topics": [{"source_key": "private", "name": "Private"}],
            },
        )
        self.sync()
        tutorial = Tutorial.objects.get(source_key=HELP)
        tutorial.topics.add(TutorialTopic.objects.create(name="Local topic"))
        tutorial.assigned_users.add(self.learner)
        tutorial.assigned_groups.add(Group.objects.create(name="Local group"))
        permissions = UserPolicyManager(self.admin)
        full_access = permissions.has_access_to_object

        def hide_topic(record: Any, *args: Any, **kwargs: Any) -> bool:
            """Deny the private topic key and delegate other reads to the real manager."""
            if (
                isinstance(record, TutorialTopic)
                and record.source_key == "django.contrib.auth:private"
            ):
                self.assertEqual(kwargs["fields"], ["source_key"])
                return False
            return full_access(record, *args, **kwargs)

        with patch.object(permissions, "has_access_to_object", side_effect=hide_topic):
            exported = tutorial.get_export_data(permissions)["tutorial"]
        self.assertEqual(exported["topics"], ["bloomerp:getting-started"])
        self.assertEqual(exported["user_filter"], self.audience_filter)
        self.assertTrue(exported["available_to_all"])
        self.assertNotIn("assigned_users", exported)
        self.assertNotIn("assigned_groups", exported)
        self.assertEqual(exported["revisions"][0]["steps"][0]["name"], "Welcome")
        local = Tutorial.objects.create(name="New locally authored tutorial")
        self.assertIsNone(local.get_export_data(permissions)["tutorial"]["source_key"])

    def test_command_includes_tutorials_for_selected_and_all_domains(self) -> None:
        """Run the tutorial synchronizer in both supported command forms."""
        module = "bloomerp.management.commands.sync_defaults"
        with (
            patch(f"{module}.create_or_update_default_tiles", return_value=[]) as tiles,
            patch(f"{module}.sync_default_policies", return_value={}) as policies,
        ):
            self.sync()
            tiles.assert_not_called()
            policies.assert_not_called()
            Tutorial.objects.filter(source_key=WELCOME).delete()
            call_command("sync_defaults", stdout=StringIO())
            self.assertTrue(Tutorial.objects.filter(source_key=WELCOME).exists())
            tiles.assert_called_once_with()
            policies.assert_called_once_with()
