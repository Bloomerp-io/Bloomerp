from django.shortcuts import render
from bloomerp.models import Widget
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import Link, Workspace
from bloomerp.utils.router import BloomerpRouter
from bloomerp.views.mixins import HtmxMixin
from django.shortcuts import get_object_or_404

router = BloomerpRouter()	

@router.bloomerp_route(
    path='',
    name='Bloomerp Dashboard',
    description='The dashboard for the Bloomerp app',
    route_type='app',
    url_name='bloomerp_home_view'
)
class BloomerpHomeView(HtmxMixin, LoginRequiredMixin, View):
    template_name = 'workspace_views/bloomerp_workspace_view.html'

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        widget_list = Widget.objects.all()
        context['widget_list'] = widget_list

        # Create a workspace for the user if it doesn't exist
        workspace = Workspace.objects.filter(user=request.user, content_type=None).first()

        if not workspace:
            workspace = Workspace.create_default_workspace(request.user)
        
        context['workspace'] = workspace
        
        return render(request, self.template_name, context)

@router.bloomerp_route(
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
        workspace_id = kwargs.get('workspace_id')
        workspace = get_object_or_404(Workspace, id=workspace_id)
        context['workspace'] = workspace
        return render(request, self.template_name, context)
    

@router.bloomerp_route(
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
        View
    ):
    model : Model = None
    template_name = 'workspace_views/bloomerp_workspace_view.html'

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        
        # Get the content type for the model
        content_type = ContentType.objects.get_for_model(self.model)
        
        workspace = Workspace.objects.filter(user=request.user, content_type=content_type).first()

        if not workspace:
            workspace = Workspace.create_default_content_type_workspace(request.user, content_type)

        context['workspace'] = workspace
        context['model_name_plural'] = self.model._meta.verbose_name_plural
        context['model'] = self.model
        return render(request, self.template_name, context)