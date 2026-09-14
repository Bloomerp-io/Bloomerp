from __future__ import annotations

from typing import Any

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q, QuerySet

from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.users.user import AbstractBloomerpUser


def clean_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``scope`` with request-style values parsed.

    Python ``None`` and the strings ``"none"`` and ``"null"`` become
    explicit ``None`` values.
    Case-insensitive ``"true"`` and ``"false"`` strings become booleans.
    Other values remain unchanged, and the input mapping is never mutated.

    Example:
        clean_scope({"module_id": "None", "enabled": "false"})
        # {"module_id": None, "enabled": False}
    """
    cleaned: dict[str, Any] = {}
    for key, value in (scope or {}).items():
        if isinstance(value, str):
            normalized_value = value.strip().lower()
            if normalized_value in {"none", "null"}:
                value = None
            elif normalized_value == "true":
                value = True
            elif normalized_value == "false":
                value = False

        cleaned[key] = value

    return cleaned


class PreferenceManager:
    """Manage the preferences available to one authenticated user.

    Shared preferences stay live: selecting one stores a lightweight reference
    to the owner's object. Creating a named preference instead copies the
    current effective values into an independently editable object.

    Example:
        manager = PreferenceManager(request.user)
        preference = manager.get_or_create_selected(
            UserObjectViewPreference,
            {"content_type_id": content_type.pk},
        )
    """

    def __init__(self, user: AbstractBloomerpUser):
        """Initialize preference management for ``user``.

        Example:
            manager = PreferenceManager(request.user)
        """
        self.user = user

    @classmethod
    def resolve_model(cls, model_name: str) -> type[BasePreference] | None:
        """Resolve a Bloomerp model name when it inherits ``BasePreference``.

        Unknown models and models outside the preference hierarchy return
        ``None``.

        Example:
            model = PreferenceManager.resolve_model("UserListViewPreference")
        """
        try:
            model = apps.get_model("bloomerp", model_name)
            if issubclass(model, BasePreference):
                return model
        except LookupError:
            pass
        return None

    def get_available(
        self,
        preference_model: type[BasePreference],
        scope: dict[str, Any] | None = None,
    ) -> QuerySet[BasePreference]:
        """Return every owned or shared preference once for a scope.

        A user-owned reference replaces its shared source in the queryset, so
        a previously selected shared preference does not appear twice.

        Example:
            preferences = manager.get_available(
                UserListViewPreference,
                {"content_type_id": content_type.pk},
            )
        """
        scope = preference_model.normalize_scope(clean_scope(scope))
        owned_references = preference_model.objects.filter(
            user=self.user,
            source_object__isnull=False,
            **scope,
        ).filter(
            Q(source_object__shared_with_users=self.user)
            | Q(source_object__shared_with_groups__user=self.user)
        )
        owned_sources = preference_model.objects.filter(
            user=self.user,
            source_object__isnull=True,
            **scope,
        )
        shared_sources = (
            preference_model.objects.filter(
                Q(shared_with_users=self.user)
                | Q(shared_with_groups__user=self.user),
                source_object__isnull=True,
                **scope,
            )
            .exclude(user=self.user)
            .exclude(pk__in=owned_references.values("source_object_id"))
        )
        qs = (
            (owned_sources | owned_references | shared_sources)
            .distinct()
            .select_related("source_object", "user")
            .order_by("name", "pk")
        )

        if preference_model.force_copy_initial_default:
            qs = qs.exclude(
                Q(initial_default=True) & ~Q(user=self.user)
            )

        return qs

    def get_or_create_selected(
        self,
        preference_model: type[BasePreference],
        scope: dict[str, Any] | None = None,
        force_create: bool = True,
    ) -> BasePreference | None:
        """Get or establish the user's effective selection for a scope.

        The lifecycle is deliberately centralized here: return an existing
        selection; otherwise select the user's first existing preference;
        otherwise reference a shared initial default; otherwise invoke the
        model's default factory. Ordinary shared preferences are not
        materialized until the user explicitly selects one.

        Example:
            preference = manager.get_or_create_selected(
                UserCreateViewPreference,
                {"content_type_id": content_type.pk},
            )
        """
        scope = preference_model.normalize_scope(clean_scope(scope))
        with transaction.atomic():
            owned = preference_model.objects.filter(
                user=self.user,
                **scope,
            ).filter(
                Q(source_object__isnull=True)
                | Q(source_object__shared_with_users=self.user)
                | Q(source_object__shared_with_groups__user=self.user)
            ).distinct().select_related("source_object").order_by("-selected", "pk")
            entry = owned.first()
            if entry is not None:
                self._select_entry(entry, scope)
                effective = entry.effective_preference
                ensure_default_state = getattr(
                    effective,
                    "ensure_default_state",
                    None,
                )
                if "content_type_id" in scope and callable(ensure_default_state):
                    ensure_default_state(
                        user=self.user,
                        content_type=ContentType.objects.get(pk=scope["content_type_id"]),
                    )
                return effective

            initial_default = self._find_initial_default(preference_model, scope)
            if initial_default is not None:
                # In cases where a deep copy is required
                if initial_default.force_copy_initial_default:
                    entry = preference_model.copy_preference_for_user(
                        user=self.user,
                        source=initial_default,
                        name=initial_default.name,
                        scope=scope,
                    )
                    self._select_entry(entry, scope)
                    return entry

                entry = self._reference(initial_default, scope)
                self._select_entry(entry, scope)
                return entry.effective_preference

            if force_create:
                entry = preference_model.create_default_for_user(self.user, **scope)
                self._select_entry(entry, scope)
                return entry.effective_preference

            return None

    def select(self, preference: BasePreference) -> BasePreference:
        """Select an available preference and return its effective object.

        Selecting a shared preference creates a user-owned reference. The
        reference remains selected while reads resolve to the owner's live
        preference object.

        Example:
            effective = manager.select(shared_preference)
            assert effective == shared_preference
        """
        preference_model = type(preference)
        scope = preference_model.normalize_scope(
            clean_scope(preference.get_scope())
        )
        with transaction.atomic():
            if preference.user_id == self.user.id:
                entry = preference
            else:
                available = self.get_available(preference_model, scope).filter(
                    pk=preference.pk
                ).exists()
                if not available:
                    raise PermissionError("This preference is not available to the user.")
                entry = self._reference(preference, scope)
            self._select_entry(entry, scope)
        return entry.effective_preference

    def create(
        self,
        preference_model: type[BasePreference],
        *,
        name: str,
        scope: dict[str, Any] | None = None,
    ) -> BasePreference:
        """Create and select an independent copy of the effective selection.

        If the scope has no selection yet, ``get_or_create_selected`` first
        applies the same initial-default or model-default lifecycle.

        Example:
            preference = manager.create(
                UserListViewPreference,
                name="Sales board",
                scope={"content_type_id": content_type.pk},
            )
        """
        scope = preference_model.normalize_scope(clean_scope(scope))
        source = self.get_or_create_selected(preference_model, scope)

        with transaction.atomic():
            created = preference_model.copy_preference_for_user(
                user=self.user,
                source=source,
                name=name.strip() or source.name,
                scope=scope,
            )
            self._select_entry(created, scope)
        return created

    def can_manage(self, preference: BasePreference) -> bool:
        """Return whether the user owns and may edit or share a preference.

        Example:
            if not manager.can_manage(preference):
                return HttpResponse(status=403)
        """
        return preference.user_id == self.user.id and not preference.source_object_id

    @staticmethod
    def can_set_initial_default(
        user: AbstractBloomerpUser,
        preference_model: type[BasePreference],
    ) -> bool:
        """Return whether ``user`` may mark a shared preference as initial.

        The model argument makes room for model-specific policy; initial
        defaults currently require superuser access for every preference type.

        Example:
            allowed = manager.can_set_initial_default(
                request.user,
                UserObjectViewPreference,
            )
        """
        return user.is_superuser

    def _find_initial_default(
        self,
        preference_model: type[BasePreference],
        scope: dict[str, Any],
    ) -> BasePreference | None:
        """Find the first shared initial default, preferring direct shares.

        Example:
            default = manager._find_initial_default(PreferenceModel, scope)
        """
        candidates = preference_model.objects.filter(
            initial_default=True,
            source_object__isnull=True,
            **scope,
        ).exclude(user=self.user)
        return (
            candidates.filter(shared_with_users=self.user).order_by("pk").first()
            or candidates.filter(shared_with_groups__user=self.user)
            .distinct()
            .order_by("pk")
            .first()
        )

    def _reference(
        self,
        preference: BasePreference,
        scope: dict[str, Any],
    ) -> BasePreference:
        """Get or create the user's lightweight reference to a shared source.

        Example:
            entry = manager._reference(shared_preference, scope)
        """
        source = preference.effective_preference
        entry, _ = type(preference).objects.get_or_create(
            user=self.user,
            source_object=source,
            defaults=scope,
        )
        return entry

    def _select_entry(
        self,
        entry: BasePreference,
        scope: dict[str, Any],
    ) -> None:
        """Make one user-owned entry the selection within its scope.

        Example:
            manager._select_entry(entry, scope)
        """
        type(entry).objects.filter(
            user=self.user,
            selected=True,
            **scope,
        ).exclude(pk=entry.pk).update(selected=False)
        if not entry.selected:
            entry.selected = True
            entry.save(update_fields=["selected"])
