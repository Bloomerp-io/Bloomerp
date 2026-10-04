"""Regression checks for the search shared by global search and object artifacts."""

from django.http import HttpRequest

from bloomerp.agents.artifacts.object import authorize_object, search_objects
from bloomerp.agents.definition import AIArtifactSearchRequest
from bloomerp.services.search_services import SearchManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestSearchManager(BaseBloomerpTestCaseWithModels):
    """Exercise real model matching, bounds and row scoping."""

    auto_create_customers = False

    def test_bounds_and_duplicate_model_scopes(self) -> None:
        """Avoid duplicate results and report only actual additional matches."""
        self.create_customer("UniqueSearch", "One", 20)
        self.create_customer("UniqueSearch", "Two", 30)
        manager = SearchManager(self.admin_user)
        limited = manager.search_objects(
            "UniqueSearch", models=[self.CustomerModel] * 2, per_model_limit=1
        )
        self.assertEqual(len(limited.items), 1)
        self.assertTrue(limited.limit_reached)
        exact = manager.search_objects(
            "UniqueSearch",
            models=[self.CustomerModel] * 2,
            per_model_limit=2,
            total_limit=2,
        )
        self.assertEqual(len(exact.items), 2)
        self.assertFalse(exact.limit_reached)

    def test_explicit_scope_cannot_grant_access(self) -> None:
        """Caller-supplied model restrictions must never widen a user's permissions."""
        self.create_customer("UniqueSearch", "One", 20)
        result = SearchManager(self.normal_user).search_objects(
            "UniqueSearch", models=[self.CustomerModel]
        )
        self.assertEqual(result.items, [])

    def test_empty_query_and_invalid_limits(self) -> None:
        """Avoid broad database scans for empty searches and reject invalid bounds."""
        manager = SearchManager(self.admin_user)
        with self.assertNumQueries(0):
            self.assertEqual(manager.search_objects("  ").items, [])
        with self.assertRaises(ValueError):
            manager.search_objects("name", total_limit=0)

    def test_artifact_adapter_uses_same_objects(self) -> None:
        """Return attachable references to the same matching records as shared search."""
        customer = self.create_customer("ArtifactSearchUnique", "One", 20)
        request = HttpRequest()
        request.user = self.admin_user
        page = search_objects(
            request, AIArtifactSearchRequest(query="ArtifactSearchUnique")
        )
        self.assertEqual(len(page.items), 1)
        self.assertEqual(page.items[0].object_id, str(customer.pk))
        authorize_object(page.items[0], request)
        request.user = self.normal_user
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            authorize_object(page.items[0], request)
