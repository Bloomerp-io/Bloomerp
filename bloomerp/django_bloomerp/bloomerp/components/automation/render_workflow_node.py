from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.router import router
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from bloomerp.models import Bookmark, AbstractBloomerpUser
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from bloomerp.utils.requests import render_blank_form

@csrf_exempt
@router.register(path='components/automation/render_workflow_node/', name='components_automation_render_workflow_node')
@login_required
def render_workflow_node(request:HttpRequest) -> HttpResponse:
    node_type = request.GET.get('node_type')
    node_sub_type = request.GET.get('node_sub_type')
    
    node = WorkflowNodeType.from_id(node_type)
    
    for st in node.value.types:
        if node_sub_type == st.id:
            node_sub_type = st
            break
    
    
    return render_blank_form(
        request,
        node_sub_type.executor_cls.config_form(),
        url=''
    )