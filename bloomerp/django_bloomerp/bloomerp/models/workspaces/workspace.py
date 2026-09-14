from bloomerp.models.mixins.default_filters_mixin import DefaultFiltersMixin
from django.utils.translation import gettext_lazy as _, gettext_noop
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Case, IntegerField, QuerySet, When
from django.urls import reverse

from bloomerp.models import BloomerpModel, FieldLayout, LayoutRow
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.models.workspaces.tile import Tile
from bloomerp.modules.definition import module_registry


class Workspace(DefaultFiltersMixin, ContentLayoutModelMixin, BasePreference):
    """A selectable, shareable workspace preference scoped by module."""

    preference_scope_fields = ("module_id",)

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
