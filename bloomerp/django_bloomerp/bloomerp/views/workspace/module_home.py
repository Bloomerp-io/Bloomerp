from django.shortcuts import redirect
from django.db.models import Q
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.router import router
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.services.workspace_services import create_default_workspace
from bloomerp.views.workspace.base_workspace_view import BaseWorkspaceView
from bloomerp.views.mixins import HtmxMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


@router.register(
    path=f"/",
    name='{module}',
    description='The homepage for the {module} module.',
    route_type='module',
    modules="__all__"
)
class BloomerpModuleHomeView(BaseWorkspaceView, HtmxMixin, LoginRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_workspace_view.html'

    def get_visible_workspaces(self):
        module_id = self.get_module_id() or ""
        return Workspace.objects.filter(
            Q(user=self.request.user) | Q(shared_with=self.request.user),
            module_id=module_id,
        ).distinct().order_by("name", "pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_workspace_template_context())
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "create_default":
            create_default_workspace(
                user=request.user,
                module_id=self.module.id,
            )
            if request.htmx:
                return HttpResponseClientRedirect(request.path)
            return redirect(request.path)

        return self.get(request, *args, **kwargs)

    def get_module_id(self) -> str | None:
        return self.module.id if self.module else None

    def get_sub_module_id(self) -> str | None:
        return None

    def get_workspace(self) -> Workspace | None:
        module_id = self.get_module_id() or ""
        workspace = Workspace.get_default_for_user(self.request.user, module_id=module_id)
        if workspace:
            return workspace
        return self.get_visible_workspaces().first()
