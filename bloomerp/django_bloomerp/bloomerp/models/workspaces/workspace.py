from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, IntegerField, QuerySet, When
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.workspaces.tile import Tile

class Workspace(AbsoluteUrlModelMixin, models.Model):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_workspace'
        constraints = [
            models.UniqueConstraint(
                fields=["user", "module_id"],
                condition=models.Q(is_default=True),
                name="unique_default_workspace_per_user_module_context",
            ),
        ]

    name = models.CharField(
        max_length=255,
        default=_("Default")
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
        )
    module_id = models.CharField(
        max_length=255, 
        default=""
        )
    layout = models.JSONField(default=dict)
    is_default = models.BooleanField(
        help_text=_("Whether it is a default workspace"),
        default=False
    )
    shared_with = models.ManyToManyField(
        to=settings.AUTH_USER_MODEL,
        related_name="shared_workspaces"
    )

    def __str__(self):
        return self.name

    @classmethod
    def get_default_for_user(cls, user, module_id: str = ""):
        return cls.objects.filter(
            user=user,
            module_id=module_id,
            is_default=True,
        ).order_by("pk").first()

    @classmethod
    def get_or_create_for_user(cls, user, module_id: str = ""):
        from bloomerp.services.sectioned_layout_services import get_default_workspace_layout, layout_has_items

        workspace = cls.get_default_for_user(
            user=user,
            module_id=module_id,
        )
        if workspace:
            if not layout_has_items(workspace.layout):
                workspace.layout = get_default_workspace_layout().model_dump()
                workspace.save(update_fields=["layout"])
            return workspace
        return cls.objects.create(
            name=str(_("Default")),
            user=user,
            module_id=module_id,
            layout=get_default_workspace_layout().model_dump(),
            is_default=True,
        )

    @property
    def layout_obj(self):
        from bloomerp.services.sectioned_layout_services import normalize_layout_payload
        return normalize_layout_payload(self.layout)
    
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
    
    
