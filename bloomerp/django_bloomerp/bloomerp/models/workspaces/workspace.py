from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Case, IntegerField, QuerySet, When
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.translation import gettext_lazy as _, gettext_noop
from django_htmx.http import HttpResponseLocation

from bloomerp.lookups.builtins.utils import no_value_form_factory
from bloomerp.lookups.definition import CompiledLookup, LookupDefinition
from bloomerp.middleware import current_request
from bloomerp.models import BloomerpModel, FieldLayout, LayoutRow
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    DataviewAction,
    DataviewActionContext,
    DataviewActionDefinition,
    ModelViewSettings,
    ObjectAction,
    ObjectActionContext,
    ObjectActionDefinition,
    StringSearchSettings,
    get_default_dataview_actions,
)
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.models.mixins.default_filters_mixin import DefaultFiltersMixin
from bloomerp.models.actions.object.builtins import get_default_object_actions
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.workspaces.tile import Tile
from bloomerp.modules.definition import module_registry


def available_workspace_filter(
    _field: ApplicationField, field_path: str, _expression: str, value: bool,
) -> CompiledLookup:
    """Match the live workspace behind each preference available to the current user."""
    from bloomerp.services.preference_services import PreferenceManager

    user = getattr(current_request(), "user", None)
    if user is None or not user.is_authenticated:
        raise ValidationError("Workspace availability requires a signed-in user")
    available_ids = PreferenceManager(user).get_available(Workspace).order_by().annotate(
        effective_id=Coalesce("source_object_id", "pk"),
    ).values("effective_id")
    predicate = models.Q(**{f"{field_path}__in": available_ids})
    return CompiledLookup(predicate=predicate if value else ~predicate)


def open_workspace_attrs(context: ObjectActionContext) -> dict[str, str]:
    """Link a workspace card to its full workspace view."""
    url = context.object.get_absolute_url()
    return {"href": url, "hx-get": url, "hx-target": "#main-content", "hx-push-url": "true"}


def open_workspace_create_view(_context: DataviewActionContext) -> HttpResponseLocation:
    """Navigate to the workspace creation page through HTMX."""
    return HttpResponseLocation(reverse("workspaces_add"), target="#main-content")


AVAILABLE_WORKSPACE = LookupDefinition(
    id="workspace_available",
    label=gettext_noop("Available workspace"),
    expressions=("workspace_available",),
    q_factory=available_workspace_filter,
    default_form_factory=no_value_form_factory,
)
OPEN_WORKSPACE = ObjectAction(
    id="open-workspace",
    label=gettext_noop("Open workspace"),
    button_attrs=open_workspace_attrs,
)
CREATE_WORKSPACE = DataviewAction(
    id="add",
    label=gettext_noop("Create"),
    icon="fa fa-plus",
    execution_func=open_workspace_create_view,
    method="GET",
    button_attrs={"hx-target": "#main-content"},
)


def workspace_object_actions(model: type[models.Model]) -> list[ObjectActionDefinition]:
    """Register the workspace link alongside the model's standard actions."""
    return [OPEN_WORKSPACE, *get_default_object_actions(model)]


def workspace_dataview_actions(model: type[models.Model]) -> list[DataviewActionDefinition]:
    """Use the personal workspace form for the toolbar's create action."""
    return [CREATE_WORKSPACE, *get_default_dataview_actions(model, skip=("add",))]


class Workspace(DefaultFiltersMixin, ContentLayoutModelMixin, BasePreference):
    """A selectable, shareable workspace preference scoped by module."""

    preference_scope_fields = ("module_id",)
    filter_lookups = {"id": (AVAILABLE_WORKSPACE,)}
    bloomerp_config = BasePreference.bloomerp_config.model_copy(update={
        "model_view_settings": ModelViewSettings(dataview_actions=workspace_dataview_actions),
        "object_actions": workspace_object_actions,
        "string_search_settings": StringSearchSettings(string_search_fields=["name"]),
    })

    class Meta(BloomerpModel.Meta):
        verbose_name = _("Workspace")
        verbose_name_plural = _("Workspaces")
        managed = True
        db_table = "bloomerp_workspace"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "module_id"],
                condition=models.Q(selected=True, module_id__isnull=False),
                name="unique_selected_workspace_per_user_module",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(selected=True, module_id__isnull=True),
                name="unique_selected_general_workspace_per_user",
            ),
            models.UniqueConstraint(
                fields=["user", "source_object"],
                condition=models.Q(source_object__isnull=False),
                name="unique_workspace_preference_reference",
            ),
        ]

    module_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        default=None,
        verbose_name=_("Module ID"),
    )

    def __str__(self):
        return self.name

    def get_filter_scope(self) -> tuple[str, str]:
        return 'workspace', str(self.pk)

    @classmethod
    def create_default_for_user(
        cls,
        user: AbstractBloomerpUser,
        **scope,
    ) -> "Workspace":
        """Create the default workspace for a user's module scope.

        Example:
            workspace = Workspace.create_default_for_user(
                user,
                module_id="sales",
            )
        """
        module_id = scope.get("module_id")
        module = module_registry.get(module_id) if module_id else None

        if module is not None and module.workspaces:
            from bloomerp.services.workspace_services import create_or_update_default_tiles

            tiles_by_native_id = create_or_update_default_tiles(
                registry=module_registry,
            )
            selected_workspace = None

            with transaction.atomic():
                for workspace_definition in module.workspaces:
                    layout = workspace_definition.model_copy(deep=True)
                    for row in layout.rows:
                        for item in row.items:
                            native_tile_id = str(item.id).strip()
                            tile = tiles_by_native_id.get(native_tile_id)
                            if tile is None:
                                raise ValueError(
                                    f"Workspace '{workspace_definition.name}' references "
                                    f"unknown tile id '{native_tile_id}'."
                                )
                            item.id = str(tile.pk)

                    workspace = cls.objects.create(
                        user=user,
                        name=workspace_definition.name,
                        module_id=module_id,
                        layout=layout.model_dump(mode="json"),
                        selected=workspace_definition.is_default,
                    )
                    if workspace.selected:
                        selected_workspace = workspace

            if selected_workspace is None:
                raise ValueError(
                    f"Module '{module_id}' does not define a default workspace."
                )
            return selected_workspace

        return cls.objects.create(
            user=user,
            name="Default",
            module_id=scope.get("module_id"),
            layout=FieldLayout(
                rows=[LayoutRow(columns=4, title=gettext_noop("My Workspace"), items=[])]
            ).model_dump(),
            selected=True,
        )

    @classmethod
    @transaction.atomic
    def copy_preference_for_user(
        cls,
        *,
        user: AbstractBloomerpUser,
        source: "Workspace",
        name: str,
        scope: dict[str, Any] | None = None,
    ) -> "Workspace":
        """Copy a workspace and its serialized layout."""
        preference = cls._create_preference_copy(
            user=user,
            source=source,
            name=name,
            scope=scope,
        )
        source.copy_default_filters_to(preference)
        return preference

    def get_absolute_url(self):
        return reverse("workspace", kwargs={"pk": self.pk})

    def get_tiles(self) -> QuerySet[Tile]:
        """Returns the tiles that are on this workspace

        Returns:
            QuerySet[Tile]: the tiles available on this
        """
        tile_ids: list[Any] = []
        seen_tile_ids: set[Any] = set()

        for row in self.layout_obj.rows:
            for item in row.items:
                try:
                    tile_id = Tile._meta.pk.to_python(item.id)
                except (TypeError, ValueError, ValidationError):
                    continue

                if tile_id in seen_tile_ids:
                    continue

                tile_ids.append(tile_id)
                seen_tile_ids.add(tile_id)

        if not tile_ids:
            return Tile.objects.none()

        preserved_order = Case(
            *[
                When(pk=tile_id, then=position)
                for position, tile_id in enumerate(tile_ids)
            ],
            output_field=IntegerField(),
        )

        return Tile.objects.filter(pk__in=tile_ids).order_by(preserved_order)
