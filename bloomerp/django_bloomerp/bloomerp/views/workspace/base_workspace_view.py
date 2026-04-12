

from abc import abstractmethod
from typing import Optional

from django.db.models import Q
from django.urls import reverse

from bloomerp.modules.definition import module_registry
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.services.sectioned_layout_services import dump_layout_json
from bloomerp.utils.models import get_create_view_url

class BaseWorkspaceView:

    @abstractmethod
    def get_module_id(self) -> Optional[str]:
        pass

    @abstractmethod
    def get_sub_module_id(self) -> Optional[str]:
        pass

    @abstractmethod
    def get_workspace(self) -> Optional[Workspace]:
        pass

    def get_visible_workspaces(self):
        return Workspace.objects.filter(
            Q(user=self.request.user) | Q(shared_with=self.request.user)
        ).distinct().order_by("name", "pk")

    def get_fallback_workspace(self) -> Optional[Workspace]:
        return self.get_visible_workspaces().first()

    def get_workspace_badges(self, workspace: Workspace) -> list[dict[str, str]]:
        module = module_registry.get_all().get(workspace.module_id) if workspace.module_id else None
        submodule = None
        if module and workspace.sub_module_id:
            submodule = next(
                (item for item in module.sub_modules if item.id == workspace.sub_module_id),
                None,
            )

        badges: list[dict[str, str]] = []
        if module:
            badges.append({"label": module.name, "tone": "module"})
        else:
            badges.append({"label": "General", "tone": "general"})

        if submodule:
            badges.append({"label": submodule.name, "tone": "submodule"})

        if workspace.user_id != self.request.user.id:
            badges.append({"label": "Shared", "tone": "shared"})

        return badges

    def build_workspace_item(self, workspace: Workspace) -> dict:
        return {
            "workspace": workspace,
            "is_shared": workspace.user_id != self.request.user.id,
            "badges": self.get_workspace_badges(workspace),
        }

    def get_create_url(self) -> str:
        url = reverse(get_create_view_url(Workspace, "relative"))
        params = []

        module_id = self.get_module_id()
        sub_module_id = self.get_sub_module_id()

        if module_id:
            params.append(f"module_id={module_id}")
        if sub_module_id:
            params.append(f"sub_module_id={sub_module_id}")

        if params:
            return f"{url}?{'&'.join(params)}"
        return url

    def get_workspace_template_context(self) -> dict:
        workspace = self.get_workspace()
        visible_workspaces = [self.build_workspace_item(item) for item in self.get_visible_workspaces()]

        context = {
            "workspace": workspace,
            "available_workspaces": visible_workspaces,
            "create_url": self.get_create_url(),
            "my_workspaces_url": reverse("my_workspaces"),
            "module_id": self.get_module_id(),
            "sub_module_id": self.get_sub_module_id(),
        }

        if workspace:
            context["workspace_layout_json"] = dump_layout_json(workspace.layout_obj)

        return context
        
