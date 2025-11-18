from django.shortcuts import render
from bloomerp.models import Widget
from django.views import View
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import Link, Workspace
from shared_utils.router.view_router import BloomerpRouter
from bloomerp.views.mixins import HtmxMixin
from django.shortcuts import get_object_or_404
from registries.route_registry import router


@router.register(
    path="/",
    name='Bloomerp Dashboard',
    description='The dashboard for the Bloomerp app',
    route_type='app',
    url_name='bloomerp_home_view'
)
class BloomerpHomeView(HtmxMixin, LoginRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_workspace_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        widget_list = Widget.objects.all()
        context['widget_list'] = widget_list

        # Create a workspace for the user if it doesn't exist
        return context

@router.register(
    path='workspace/<int:workspace_id>/',
    name='View Workspace',
    description='View a workspace',
    route_type='app',
    url_name='view_workspace'
)
class WorkspaceView(HtmxMixin, LoginRequiredMixin, View):
    template_name = 'workspace_views/bloomerp_workspace_view.html'

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        
        return render(request, self.template_name, context)
    

@router.register(
        models="__all__",
        path='',
        name='{model} Dashboard',
        description='The dashboard for the {model} model',
        route_type = 'list',
        url_name='dashboard'
)
class BloomerpContentTypeWorkspaceView(
        HtmxMixin,
        LoginRequiredMixin,
        TemplateView
    ):
    model : Model = None
    template_name = 'workspace_views/bloomerp_workspace_view.html'
    
    