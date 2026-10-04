"""Shared, permission-scoped object search independent of templates and artifacts."""

from collections.abc import Iterable

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db.models import Model
from pydantic import BaseModel, ConfigDict

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.object_services import string_search_on_queryset


class ObjectSearchResult(BaseModel):
    """Return matching ORM objects and indicate that the bounded search omitted matches."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    limit_reached: bool
    items: list[Model]


class SearchManager:
    """Apply the same model eligibility, row scope and matching rules to every caller."""

    def __init__(self, user: AbstractBloomerpUser) -> None:
        """Bind object discovery to the authenticated user's permission manager."""
        self.user = user
        self.permission_manager = UserPolicyManager(user)

    @staticmethod
    def is_searchable(model: type[Model] | None) -> bool:
        """Exclude framework metadata, swapped models and models opting out of search."""
        if model is None or model in {
            ContentType,
            ApplicationField,
            Permission,
            LogEntry,
            Session,
        }:
            return False
        if model._meta.swapped:
            return False
        config = getattr(model, "bloomerp_config", None)
        return not isinstance(config, BloomerpModelConfig) or (
            not config.is_internal and config.string_search_settings.allow_global_search
        )

    def search_objects(
        self,
        query: str,
        *,
        models: Iterable[type[Model]] | None = None,
        per_model_limit: int = 5,
        total_limit: int = 40,
    ) -> ObjectSearchResult:
        """Search authorized rows with per-model and total bounds, deduplicating model scopes."""
        if per_model_limit < 1 or total_limit < 1:
            raise ValueError("Search limits must be positive")
        query = query.strip()
        if not query:
            return ObjectSearchResult(items=[], limit_reached=False)
        accessible = self.permission_manager.get_accessible_models(
            BloomerpPermission.VIEW
        )
        allowed = set(accessible)
        candidates = dict.fromkeys(accessible if models is None else models)
        items: list[Model] = []
        truncated = False
        for model in candidates:
            if model not in allowed or not self.is_searchable(model):
                continue
            remaining = total_limit - len(items)
            limit = min(per_model_limit, remaining)
            queryset = self.permission_manager.get_accessible_queryset(
                model, BloomerpPermission.VIEW
            )
            matches = list(
                string_search_on_queryset(queryset, query)
                .order_by("pk")
                .distinct()[: limit + 1]
            )
            if len(matches) > limit:
                truncated = True
            items.extend(matches[:limit])
            if len(items) == total_limit and truncated:
                break
        return ObjectSearchResult(items=items, limit_reached=truncated)
