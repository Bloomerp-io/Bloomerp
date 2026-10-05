"""Shared, permission-scoped object search independent of templates and artifacts."""

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db.models import Model
from django.utils.encoding import force_str
from pydantic import BaseModel, ConfigDict

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.modules.definition import ModuleConfig, module_registry
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.object_services import string_search_on_queryset


def _normalize_key(value: str) -> str:
    """Normalize localized search keys for case-insensitive prefix matching."""
    normalized = unicodedata.normalize("NFKC", force_str(value or ""))
    return normalized.strip().casefold().replace("-", "_")


def _ensure_module_registry_models() -> None:
    """Ensure dynamic models are mapped into the registry before scoped search."""
    try:
        module_registry._register_models_from_apps()
    except Exception:  # noqa: BLE001 - preserve the registry refresh fallback
        module_registry.refresh()


def _resolve_module(module_key: str) -> ModuleConfig | None:
    """Resolve a module by identifier, code or localized name, including prefixes."""
    _ensure_module_registry_models()
    normalized = _normalize_key(module_key)
    module = module_registry.get(normalized)
    if module:
        return module
    exact_matches = []
    partial_matches = []
    for item in module_registry.get_all().values():
        code = _normalize_key(item.code)
        name = _normalize_key(item.name)
        localized_name = _normalize_key(item.localized_name)
        module_id = _normalize_key(item.full_id or item.id)
        if normalized in {code, name, localized_name, module_id}:
            exact_matches.append(item)
        elif any(
            value.startswith(normalized)
            for value in (code, name, localized_name, module_id)
        ):
            partial_matches.append(item)
    if exact_matches:
        return exact_matches[0]
    if partial_matches:
        return partial_matches[0]
    return None


def _resolve_models_by_name(
    model_key: str, permission_manager: UserPolicyManager
) -> list[type[Model]]:
    """Resolve localized and partial model names within the user's accessible models."""
    _ensure_module_registry_models()
    normalized = _normalize_key(model_key)
    matched = []
    for model in permission_manager.get_accessible_models(BloomerpPermission.VIEW):
        model_name = _normalize_key(model._meta.model_name)
        verbose_name = _normalize_key(model._meta.verbose_name)
        verbose_name_plural = _normalize_key(model._meta.verbose_name_plural)
        if (
            model_name == normalized
            or verbose_name == normalized
            or verbose_name_plural == normalized
            or model_name.startswith(normalized)
            or verbose_name.startswith(normalized)
            or verbose_name_plural.startswith(normalized)
        ):
            matched.append(model)
    return matched


@dataclass
class ObjectSearchQuery:
    """Describe a parsed object query and the model scope requested by its prefix."""

    value: str
    models: list[type[Model]] | None = None
    search_type: str = "general"
    label: str = "All content"
    scope: dict[str, str] = field(default_factory=dict)
    error: str | None = None


class ObjectSearchResult(BaseModel):
    """Return matching ORM objects and indicate that the bounded search omitted matches."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    limit_reached: bool
    items: list[Model]
    search: ObjectSearchQuery


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

    def parse_query(self, query: str) -> ObjectSearchQuery:
        """Resolve shared slash and user prefixes without interpreting view commands."""
        query = query.strip()
        if query.startswith("@"):
            return ObjectSearchQuery(
                value=query[1:].strip(),
                models=[get_user_model()],
                search_type="users",
                label="Users",
            )
        if not query.startswith("/"):
            return ObjectSearchQuery(value=query)

        parsed = ObjectSearchQuery(
            value=query, search_type="slash", label="Module and model"
        )
        if query.startswith("///"):
            parsed.value = query[3:].strip()
            parsed.label = "All content"
        elif query.startswith("//"):
            model_key, _, parsed.value = query[2:].partition("/")
            parsed.scope = {"model": model_key}
            parsed.label = "Model search"
            parsed.models = _resolve_models_by_name(model_key, self.permission_manager)
            if not parsed.models:
                parsed.error = "Model not found."
        else:
            remainder = query[1:]
            if "//" in remainder:
                module_key, _, parsed.value = remainder.partition("//")
                parsed.label = "Module search"
                parsed.scope = {"module": module_key}
                module = _resolve_module(module_key)
                if module is None:
                    parsed.error = "Module not found."
                else:
                    parsed.scope = {"module": module.localized_name}
                    parsed.models = module_registry.get_models_for_module(
                        module.id,
                        include_descendants=True,
                    )
            else:
                parts = [part for part in remainder.split("/") if part]
                if len(parts) < 3:
                    parsed.error = "Use /<module>//<query>, //<model>/<query>, or /<module>/<model>/<query>."
                else:
                    module_key, model_key = parts[:2]
                    parsed.value = "/".join(parts[2:]).strip()
                    parsed.scope = {"module": module_key, "model": model_key}
                    module = _resolve_module(module_key)
                    if module is None:
                        parsed.error = "Module not found."
                    else:
                        module_models = set(
                            module_registry.get_models_for_module(
                                module.id,
                                include_descendants=True,
                            )
                        )
                        parsed.models = [
                            model
                            for model in _resolve_models_by_name(
                                model_key, self.permission_manager
                            )
                            if model in module_models
                        ]
                        parsed.scope = {
                            "module": module.localized_name,
                            "model": model_key,
                        }
                        if not parsed.models:
                            parsed.error = "Model not found in module."
        parsed.value = parsed.value.strip()
        return parsed

    def search_objects(
        self,
        query: str,
        *,
        models: Iterable[type[Model]] | None = None,
        per_model_limit: int = 5,
        total_limit: int = 40,
    ) -> ObjectSearchResult:
        """Search authorized rows using shared prefixes intersected with caller model restrictions."""
        if per_model_limit < 1 or total_limit < 1:
            raise ValueError("Search limits must be positive")
        parsed = self.parse_query(query)
        query = parsed.value
        if not query or parsed.error:
            return ObjectSearchResult(items=[], limit_reached=False, search=parsed)
        accessible = self.permission_manager.get_accessible_models(
            BloomerpPermission.VIEW
        )
        allowed = set(accessible)
        candidates = dict.fromkeys(
            accessible if parsed.models is None else parsed.models
        )
        if models is not None:
            caller_candidates = dict.fromkeys(models)
            candidates = dict.fromkeys(
                model for model in caller_candidates if model in candidates
            )
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
        return ObjectSearchResult(items=items, limit_reached=truncated, search=parsed)
