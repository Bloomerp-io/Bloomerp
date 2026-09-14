

from abc import abstractmethod
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet
from django.urls import reverse

from bloomerp.models import LayoutItem
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.services.sectioned_layout_services import dump_layout_json
from bloomerp.services.workspace_services import build_workspace_layout_item
from bloomerp.utils.models import get_create_view_url
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.layout_mixin import ChangeContext, LayoutMixin


class BaseWorkspaceView(LayoutMixin, BaseBloomerpView):
    template_name = "views/workspaces/bloomerp_workspace_view.html"
    
    ts_container_component = "workspace-container"
    ts_item_component = "workspace-tile"
    item_has_border = True
    
    is_visible_extractor_func = lambda _, __: True
    label_extractor_func = lambda self, item: self.get_rendered_tile_item(item).label
    content_extractor_func = lambda self, item: self.get_rendered_tile_item(item).content
    icon_extractor_func = lambda self, item: self.get_rendered_tile_item(item).icon
    edit_url_extractor_func = lambda self, item: self.get_rendered_tile_item(item).edit_url
    search_keywords_extractor_func = lambda self, item: self.get_rendered_tile_item(item).search_keywords
    
    
    tiles: QuerySet[Tile] | None = None
    rendered_tile_items: dict[str, LayoutItem] | None = None

    def get_rendered_tile_item(self, item: LayoutItem) -> LayoutItem:
        if self.rendered_tile_items is None:
            self.rendered_tile_items = {}
        item_id = str(item.id)
        if item_id not in self.rendered_tile_items:
            self.rendered_tile_items[item_id] = build_workspace_layout_item(
                tile=self.get_tile(item.id),
                request=self.request,
                colspan=item.colspan,
                config=item.config,
                workspace_id=str(self.get_workspace().effective_preference.pk),
            )
        return self.rendered_tile_items[item_id]

    def get_tile(self, id):
        if self.tiles is None:
            self.tiles = Tile.objects.all()
        return self.tiles.get(id=id)
    
    def get_change_context(self) -> ChangeContext | None:
        workspace = self.get_workspace()
        if not workspace:
            return None

        return ChangeContext(
            owner_content_type_id=ContentType.objects.get_for_model(Workspace).id,
            owner_object_id=workspace.id,
        )

    def get_can_change(self) -> bool:
        workspace = self.get_workspace()
        return bool(workspace and workspace.user_id == self.request.user.id)

    def get_layout_container_extra_attrs(self) -> dict[str, object]:
        workspace = self.get_workspace()
        return {"data-workspace-id": workspace.id} if workspace else {}
    
    @abstractmethod
    def get_module_id(self) -> Optional[str]:
        pass

    @abstractmethod
    def get_workspace(self) -> Optional[Workspace]:
        pass
    
    def build_workspace_item(self, workspace: Workspace) -> dict:
        workspace = workspace.effective_preference
        return {
            "workspace": workspace,
        }

    def get_create_url(self) -> str:
        url = reverse(get_create_view_url(Workspace, "relative"))
        params = []

        module_id = self.get_module_id()

        if module_id:
            params.append(f"module_id={module_id}")

        if params:
            return f"{url}?{'&'.join(params)}"
        return url

    def get_workspace_template_context(self) -> dict:
        workspace = self.get_workspace()
        if workspace:
            workspace = workspace.effective_preference
        
        
        context = {
            "workspace": workspace,
            "create_url": self.get_create_url(),
            "my_workspaces_url": reverse("my_workspaces"),
            "module_id": self.get_module_id(),
            "workspace_is_selected": bool(
                workspace
                and Workspace.objects.filter(
                    user=self.request.user,
                    module_id=workspace.module_id,
                    selected=True,
                )
                .filter(Q(pk=workspace.pk) | Q(source_object_id=workspace.pk))
                .exists()
            ),
            "workspace_content_type_id" : ContentType.objects.get_for_model(Workspace),
            "extra_attrs" : {"data-workspace-id": workspace.id if workspace else None},
            "preference_args" : {"module_id": self.get_module_id()}
        }

        if workspace:
            context["workspace_layout_json"] = dump_layout_json(workspace.layout_obj)

        return context
        
    def get_layout(self):
        workspace = self.get_workspace()
        return workspace.layout_obj if workspace else None
