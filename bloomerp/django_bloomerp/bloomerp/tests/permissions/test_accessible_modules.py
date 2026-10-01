"""Shared module discovery for artifacts and the workspace home page."""

from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser

from bloomerp.modules.definition import ModuleConfig, module_registry
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestAccessibleModules(BaseBloomerpTestCaseWithModels):
    """Check visibility, descendant membership and requested permission propagation."""

    auto_create_customers = False

    def test_modules_follow_accessible_descendant_models(self) -> None:
        """Allow a parent through descendant model access, excluding hidden/disabled modules."""
        root = ModuleConfig(id="root", code="root", name="Root")
        child = ModuleConfig(
            id="child",
            full_id="root.child",
            parent_module_id="root",
            code="child",
            name="Child",
        )
        hidden = ModuleConfig(id="hidden", code="hidden", name="Hidden", visible=False)
        disabled = ModuleConfig(
            id="disabled", code="disabled", name="Disabled", enabled=False
        )
        with (
            patch.object(
                module_registry,
                "items",
                {
                    item.full_id or item.id: item
                    for item in [root, child, hidden, disabled]
                },
            ),
            patch.object(
                module_registry,
                "get_models_for_module",
                return_value=[self.CustomerModel],
            ) as models,
            patch.object(
                UserPolicyManager,
                "get_accessible_models",
                return_value=[self.CustomerModel],
            ) as accessible,
        ):
            result = UserPolicyManager(self.normal_user).get_accessible_modules(
                BloomerpPermission.VIEW, PermissionMatch.ALL
            )
        self.assertEqual(result, [root, child])
        accessible.assert_called_once_with(BloomerpPermission.VIEW, PermissionMatch.ALL)
        models.assert_any_call("root.child", include_descendants=True)

    def test_no_access_and_anonymous(self) -> None:
        """Return no modules for users without matching model grants or authentication."""
        self.assertEqual(
            UserPolicyManager(self.normal_user).get_accessible_modules(
                BloomerpPermission.VIEW
            ),
            [],
        )
        with self.assertNumQueries(0):
            self.assertEqual(
                UserPolicyManager(AnonymousUser()).get_accessible_modules(
                    BloomerpPermission.VIEW
                ),
                [],
            )

    def test_superuser_sees_visible_enabled_empty_modules(self) -> None:
        """Preserve superuser module discovery even before any models are assigned."""
        visible = ModuleConfig(id="empty", code="empty", name="Empty")
        hidden = ModuleConfig(id="hidden", code="hidden", name="Hidden", visible=False)
        with (
            patch.object(
                module_registry, "items", {"empty": visible, "hidden": hidden}
            ),
            patch.object(module_registry, "get_models_for_module", return_value=[]),
        ):
            self.assertEqual(
                UserPolicyManager(self.admin_user).get_accessible_modules(
                    BloomerpPermission.VIEW
                ),
                [visible],
            )
