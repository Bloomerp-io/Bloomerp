"""Verify policy-aware model attachment discovery and selection reauthorization."""

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase

from bloomerp.agents.artifacts.model import (
    MODEL_ARTIFACT,
    ModelArtifactPayload,
    authorize_model,
    search_models,
)
from bloomerp.agents.artifacts.selection import resolve_selection, selection_item
from bloomerp.agents.definition import AIArtifactSearchRequest
from bloomerp.components.agents.search_artifacts import search_artifacts
from bloomerp.models import File
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager


class ModelArtifactTests(TestCase):
    """Exercise actual stored grants rather than mocking the permission manager."""

    def setUp(self) -> None:
        """Create an unprivileged user and an initially unassigned view policy."""
        self.user = get_user_model().objects.create_user(username="model-picker-user")
        self.request = RequestFactory().get(
            "/", {"type": "model", "q": File._meta.label}
        )
        self.request.user = self.user
        self.policy = PolicyManager.create_policy(
            File,
            AccessRule(
                row_permissions=[RowPolicyRuleContent(permissions=["view"])],
                field_permissions={},
            ),
        )

    def test_direct_and_group_policies_enable_model_selection(self) -> None:
        """Discover viewable models from both direct assignments and group policies."""
        group = Group.objects.create(name="model-picker-group")
        self.user.groups.add(group)
        for assignee in (self.user, group):
            with self.subTest(assignee=type(assignee).__name__):
                self.policy.users.clear()
                self.policy.groups.clear()
                PolicyManager.assign(self.policy, assignee)
                response = search_artifacts(self.request)
                self.assertEqual(response.status_code, 200)
                items = json.loads(response.content)["items"]
                self.assertEqual([item["title"] for item in items], [File._meta.label])
                resolved = resolve_selection(items[0]["token"], self.request)
                self.assertEqual(resolved["payload"], {"model_label": File._meta.label})

    def test_unprivileged_and_anonymous_users_have_no_models(self) -> None:
        """Hide model metadata from users without grants and anonymous callers."""
        for user in (self.user, AnonymousUser()):
            with self.subTest(user=str(user)):
                self.request.user = user
                self.assertEqual(
                    search_models(self.request, AIArtifactSearchRequest()).items, []
                )
                with self.assertRaises(PermissionDenied):
                    authorize_model(
                        ModelArtifactPayload(model_label=File._meta.label), self.request
                    )

    def test_revoked_policy_rejects_signed_selection(self) -> None:
        """Recheck current grants even when a candidate token was previously signed."""
        PolicyManager.assign(self.policy, self.user)
        candidate = selection_item(
            MODEL_ARTIFACT,
            ModelArtifactPayload(model_label=File._meta.label),
            self.request,
        )
        self.policy.users.clear()
        with self.assertRaises(PermissionDenied):
            resolve_selection(candidate["token"], self.request)

    def test_superuser_search_is_filtered_and_paginated(self) -> None:
        """Search display names case-insensitively and paginate without duplicate labels."""
        self.user.is_superuser = True
        page = search_models(
            self.request,
            AIArtifactSearchRequest(query=str(File._meta.verbose_name_plural).upper()),
        )
        self.assertIn(File._meta.label, [item.model_label for item in page.items])
        expected = sorted(
            content_type.model_class()._meta.label
            for content_type in ContentType.objects.all()
            if content_type.model_class() is not None
        )
        labels: list[str] = []
        cursor: str | None = None
        while True:
            page = search_models(
                self.request, AIArtifactSearchRequest(limit=2, cursor=cursor)
            )
            labels.extend(item.model_label for item in page.items)
            cursor = page.cursor
            if cursor is None:
                break
        self.assertEqual(labels, expected)

    def test_stale_content_type_is_not_attachable(self) -> None:
        """Ignore removed models even when their content types remain in the database."""
        self.user.is_superuser = True
        ContentType.objects.create(app_label="removed", model="missing")
        self.assertEqual(
            search_models(
                self.request, AIArtifactSearchRequest(query="removed.missing")
            ).items,
            [],
        )
        with self.assertRaises(PermissionDenied):
            authorize_model(
                ModelArtifactPayload(model_label="removed.Missing"), self.request
            )
