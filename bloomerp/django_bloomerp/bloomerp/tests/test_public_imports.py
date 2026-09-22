"""Contracts for the package imports used by Bloomerp app developers."""

from importlib import import_module

from django.test import SimpleTestCase


class PublicImportsTestCase(SimpleTestCase):
    def test_documented_package_exports_resolve(self) -> None:
        """
        Use case: An app imports common extension points from package roots.
        Expected result: Every advertised symbol resolves to its source object.
        """
        # 1. Import the packages used when defining app models and extensions.
        packages = (
            "permissions", "models", "filters", "automation", "dataviews",
            "lookups", "form_behaviors", "views",
        )
        expected = {
            "permissions": ("BloomerpPermission", "PolicyManager", "UserPolicyManager"),
            "models": ("BloomerpModel", "BloomerpModelConfig"),
            "filters": ("Filter", "FilterCondition", "Filters", "ModelFilterManager"),
            "automation": ("WorkflowNodeDefinition", "WORKFLOW_NODE_REGISTRY"),
            "dataviews": ("BaseDataview", "DATAVIEW_REGISTRY", "TableDataView"),
            "lookups": ("LookupDefinition", "LOOKUP_REGISTRY", "BUILTIN_LOOKUPS"),
            "form_behaviors": ("BehaviorActionDefinition", "ACTION_REGISTRY", "SET_VALUE"),
            "views": ("BaseBloomerpView", "BloomerpCreateView", "BloomerpListView"),
        }

        # 2. Check the advertised API and resolve each public symbol.
        for package_name in packages:
            with self.subTest(package=package_name):
                package = import_module(f"bloomerp.{package_name}")
                for name in expected[package_name]:
                    with self.subTest(symbol=name):
                        self.assertTrue(hasattr(package, name))
                for name in getattr(package, "__all__", ()):
                    with self.subTest(symbol=name):
                        self.assertTrue(hasattr(package, name))
