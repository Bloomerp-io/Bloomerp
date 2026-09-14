from django.utils.translation import gettext_lazy as _
from abc import ABCMeta, abstractmethod
from copy import deepcopy
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.db.models.base import ModelBase

from bloomerp.lookups import builtins as lookups
from bloomerp.models.definition import ApiAccessSettings, ApiSettings, BloomerpModelConfig
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.users.user import AbstractBloomerpUser

BASE_PREFERENCE_FIELD_NAMES = {
    "id",
    "pk",
    "user",
    "user_id",
    "name",
    "selected",
    "source_object",
    "source_object_id",
    "shared_with_users",
    "shared_with_groups",
    "initial_default",
}


class AbstractPreferenceModelBase(ModelBase, ABCMeta):
    """Combine Django model construction with Python abstract methods."""


class BasePreference(
    AbsoluteUrlModelMixin,
    models.Model,
    metaclass=AbstractPreferenceModelBase,
):
    """
    Abstract base model for user preferences.
    This model is intended to be inherited by other models that represent specific user preferences.
    """
    class Meta:
        abstract = True

    # Subclasses declare the fields that partition a user's selections, for
    # example ("content_type",) for view preferences or ("module_id",) for
    # workspace preferences.
    preference_scope_fields: tuple[str, ...] = ()

    # When set to true, rather than creating a reference
    # to the object, the source object is copied into a new
    # object owned by the user copying from it
    # This also disallows the user from referencing to it
    force_copy_initial_default: bool = False

    bloomerp_config = BloomerpModelConfig(
        api_settings=ApiSettings(
            enable_auto_generation=True,
            access=ApiAccessSettings(
                authenticated=[
                    AccessRule(
                        row_permissions=[
                            RowPolicyRuleContent(
                                permissions=[
                                    BloomerpPermission.VIEW,
                                    BloomerpPermission.CHANGE,
                                ],
                                conditions=[
                                    RowPolicyRuleCondition(
                                        field="user",
                                        operator=lookups.EQUALS_USER.id,
                                        value="$user",
                                    )
                                ],
                            )
                        ],
                        field_permissions={
                            "id": [BloomerpPermission.VIEW],
                            "name": [
                                BloomerpPermission.VIEW,
                                BloomerpPermission.CHANGE,
                            ],
                        },
                    )
                ]
            ),
        ),
    )

    name = models.CharField(
        max_length=255,
        help_text="Optional name for this preference, for user reference",
        default="Default",
        verbose_name=_("Name"),
    )
    user = models.ForeignKey(
        to=settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(class)s_preferences",
        verbose_name=_("User"),
    )
    selected = models.BooleanField(
        default=False,
        help_text=(
            "Indicates if this preference is currently selected for the user. "
            "Only one preference per user can be selected at a time."
        ),
        verbose_name=_("Selected"),
    )
    source_object = models.ForeignKey(
        to="self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="derived_%(class)s_preferences",
        help_text=(
            "Reference to the original preference from which this preference was derived. "
            "This is used to track the origin of derived preferences."
        ),
        verbose_name=_("Source Object"),
    )

    # Fields for sharing preferences with other users
    shared_with_users = models.ManyToManyField(
        to=settings.AUTH_USER_MODEL,
        related_name="shared_%(class)s_preferences",
        blank=True,
        help_text="Users with whom this preference is shared.",
        verbose_name=_("Shared With Users"),
    )
    shared_with_groups = models.ManyToManyField(
        to="auth.Group",
        related_name="shared_%(class)s_preferences",
        blank=True,
        help_text="Groups with whom this preference is shared.",
        verbose_name=_("Shared With Groups"),
    )
    initial_default = models.BooleanField(
        default=False,
        help_text=(
            "Indicates if this preference is the initial default for the user. "
            "This is used to determine the user's default preference when they first create an account."
        ),
        verbose_name=_("Initial Default"),
    )

    @classmethod
    @abstractmethod
    def copy_preference_for_user(
        cls,
        *,
        user: AbstractBloomerpUser,
        source: "BasePreference",
        name: str,
        scope: dict[str, Any] | None = None,
    ) -> "BasePreference":
        """Copy ``source`` into an independent preference owned by ``user``.

        Subclasses implement this hook explicitly so relational configuration
        can be copied where necessary.
        """
        raise NotImplementedError(
            "Subclasses must implement copy_preference_for_user method."
        )

    @classmethod
    def _copy_values(cls, source: "BasePreference") -> dict[str, Any]:
        """Deep-copy concrete configuration values for a new preference.

        Ownership, sharing, selection, identity, and source-reference fields
        are excluded.
        """
        values: dict[str, Any] = {}
        for field in source._meta.concrete_fields:
            if (
                field.primary_key
                or field.auto_created
                or field.name in BASE_PREFERENCE_FIELD_NAMES
            ):
                continue
            key = field.attname if field.many_to_one else field.name
            values[key] = deepcopy(getattr(source, key))
        return values

    @classmethod
    def _create_preference_copy(
        cls,
        *,
        user: AbstractBloomerpUser,
        source: "BasePreference",
        name: str,
        scope: dict[str, Any] | None = None,
    ) -> "BasePreference":
        """Create the independent model row used by subclass copy hooks."""
        values = cls._copy_values(source)
        values.update(scope or {})
        values.update(
            user=user,
            name=name,
            selected=False,
            source_object=None,
            initial_default=False,
        )
        return cls.objects.create(**values)

    @classmethod
    @abstractmethod
    def create_default_for_user(
        cls,
        user: AbstractBloomerpUser,
        **scope,
    ) -> "BasePreference":
        """Create a default preference for a user within a normalized scope.

        Subclasses implement this factory and declare the accepted scope keys
        through ``preference_scope_fields``. For example, a view preference
        receives ``content_type_id=12``, while a workspace preference could
        receive ``module_id="sales"``.

        Example:
            preference = PreferenceModel.create_default_for_user(
                user,
                content_type_id=content_type.pk,
            )
        """
        raise NotImplementedError(
            "Subclasses must implement create_default_for_user method."
        )

    @classmethod
    def normalize_scope(cls, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return this preference model's scope values from arbitrary input.

        Foreign-key fields are normalized to their Django ``*_id`` names and
        unrelated request parameters are ignored.

        Example:
            scope = UserObjectViewPreference.normalize_scope(
                {"content_type_id": "12", "page": "2"}
            )
            # {"content_type_id": "12"}
        """
        params = params or {}
        scope: dict[str, Any] = {}
        for field_name in cls.preference_scope_fields:
            field = cls._meta.get_field(field_name)
            for identifier in (field.name, field.attname):
                if identifier not in params:
                    continue
                value = params[identifier]
                if value == "":
                    continue
                scope[field.attname] = value
                break
        return scope

    def get_scope(self) -> dict[str, Any]:
        """Return the normalized scope represented by this preference.

        Example:
            preference.get_scope()
            # {"content_type_id": 12}
        """
        return {
            self._meta.get_field(field_name).attname: getattr(
                self,
                self._meta.get_field(field_name).attname,
            )
            for field_name in self.preference_scope_fields
        }

    def select(self) -> None:
        """Select this preference within its user and model-defined scope.

        Example:
            preference.select()
        """
        if not self.user_id:
            raise ValueError("A preference must have a user before it can be selected.")

        self.selected = True
        self.save(update_fields=["selected"])

    def save(self, *args, **kwargs):
        """Persist the preference while enforcing one selection per scope.

        Selecting a preference deselects every sibling belonging to the same
        user and scope. If a scope has no selection after saving, its first
        saved preference becomes selected, preserving the existing preference
        behavior.

        Example:
            preference.selected = True
            preference.save(update_fields=["selected"])
        """
        if not self.user_id:
            return super().save(*args, **kwargs)

        scope = self.get_scope()
        with transaction.atomic():
            if self.selected:
                self._selection_queryset(scope).exclude(pk=self.pk).update(
                    selected=False
                )

            result = super().save(*args, **kwargs)
            selections = self._selection_queryset(scope)

            if self.selected:
                selections.exclude(pk=self.pk).update(selected=False)
            elif not selections.exists():
                type(self).objects.filter(pk=self.pk).update(selected=True)
                self.selected = True

        return result

    def _selection_queryset(self, scope: dict[str, Any]):
        """Return selected siblings for this preference's user and scope."""
        return type(self).objects.filter(
            user_id=self.user_id,
            selected=True,
            **scope,
        )

    @property
    def effective_preference(self) -> "BasePreference":
        """Return the preference that supplies this preference's live state."""
        preference = self
        seen_ids: set[int] = set()
        while preference.source_object_id:
            if preference.pk in seen_ids:
                break
            seen_ids.add(preference.pk)
            preference = preference.source_object
        return preference
