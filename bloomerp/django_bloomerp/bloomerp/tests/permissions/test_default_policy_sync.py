"""Tests for policies declared by model configuration."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from bloomerp.models.access_control.policy import Policy
from bloomerp.models.definition import BloomerpModelConfig, DefaultPolicy, PermissionSettings
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.definition import AccessRule, BloomerpPermission, RowPolicyRuleContent
from bloomerp.services.default_policy_services import sync_default_policies


class TestDefaultPolicySync(TestCase):
    """Verify persistence and updates of model-owned policy declarations."""

    def test_sync_preserves_policy_identity_and_assignments(self) -> None:
        """
        Use case: A configured policy is synchronized twice, then its rule changes.
        Expected result: One traceable policy keeps its ID and updated grants.
        """
        # 1. Configure an unconditional view grant for Todo.
        declaration = DefaultPolicy(
            id="reader", name="Todo reader", description="Can read to-dos",
            access_rule=AccessRule(
                field_permissions={"__all__": [BloomerpPermission.VIEW]},
                row_permissions=[RowPolicyRuleContent(permissions=[BloomerpPermission.VIEW])],
            ),
        )
        config = BloomerpModelConfig(
            permission_settings=PermissionSettings(default_policies=[declaration]),
        )
        with patch.object(Todo, "bloomerp_config", config):
            # 2. Repeated synchronization retains the same policy and rules.
            first = sync_default_policies([Todo])["bloomerp.todo:reader"]
            second = sync_default_policies([Todo])["bloomerp.todo:reader"]
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(first.row_policy_id, second.row_policy_id)
            self.assertTrue(second.system_created)
            self.assertEqual(
                list(second.global_permissions.values_list("codename", flat=True)),
                ["view_todo"],
            )
            self.assertEqual(second.description, "Can read to-dos")
            self.assertEqual(Policy.objects.filter(default_policy_key="bloomerp.todo:reader").count(), 1)
            group = Group.objects.create(name="To-do readers")
            second.groups.add(group)

            # 3. Changing the configured grants updates the same policy.
            declaration.access_rule.field_permissions["__all__"].append(BloomerpPermission.CHANGE)
            declaration.access_rule.row_permissions[0].permissions.append(BloomerpPermission.CHANGE)
            third = sync_default_policies([Todo])["bloomerp.todo:reader"]
            self.assertEqual(third.pk, first.pk)
            self.assertTrue(third.groups.filter(pk=group.pk).exists())
            self.assertIn("change_todo", third.field_policy.rule["__all__"])
            self.assertEqual(
                set(third.global_permissions.values_list("codename", flat=True)),
                {"view_todo", "change_todo"},
            )

    def test_duplicate_default_policy_ids_are_rejected(self) -> None:
        """
        Use case: A model declares two default policies with the same ID.
        Expected result: Configuration validation prevents an ambiguous source.
        """
        # 1. Build a valid policy declaration.
        declaration = DefaultPolicy(id="same", name="Reader", access_rule=AccessRule())
        # 2. Reject duplicate IDs before any database work.
        with self.assertRaises(ValueError):
            PermissionSettings(default_policies=[declaration, declaration])

    def test_permissions_domain_skips_tiles(self) -> None:
        """
        Use case: The operator selects the permissions domain.
        Expected result: The tile synchronization function is not called.
        """
        # 1. Stub the two domain services.
        with patch(
            "bloomerp.management.commands.sync_defaults.sync_default_policies",
            return_value={},
        ) as sync_policies, patch(
            "bloomerp.management.commands.sync_defaults.create_or_update_default_tiles",
        ) as sync_tiles:
            # 2. Invoke the command with only the permissions domain.
            call_command("sync_defaults", "permissions", stdout=StringIO())
        # 3. Confirm command routing.
        sync_policies.assert_called_once_with()
        sync_tiles.assert_not_called()

    def test_default_domain_runs_tiles_and_permissions(self) -> None:
        """
        Use case: The operator invokes sync_defaults without a domain.
        Expected result: Both tile and policy defaults are synchronized.
        """
        # 1. Stub both domain services.
        with patch(
            "bloomerp.management.commands.sync_defaults.sync_default_policies",
            return_value={},
        ) as sync_policies, patch(
            "bloomerp.management.commands.sync_defaults.create_or_update_default_tiles",
            return_value={},
        ) as sync_tiles:
            # 2. Invoke the command without a domain.
            call_command("sync_defaults", stdout=StringIO())
        # 3. Confirm both domains were processed.
        sync_policies.assert_called_once_with()
        sync_tiles.assert_called_once_with()
