from registries.route_registry import router
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import Bookmark, AbstractBloomerpUser
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

@csrf_exempt
@router.route(path='components/automation/render_workflow_node/', name='components_automation_render_workflow_node')
@login_required
def render_workflow_node(request:HttpRequest) -> HttpResponse:
    context = {}
    request.GET.get('node_type')
    request.GET.get('node_sub_type')
    
    return render(request, 'components/automation/render_workflow_node.html', context)