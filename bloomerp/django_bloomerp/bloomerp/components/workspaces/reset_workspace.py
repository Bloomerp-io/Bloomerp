from bloomerp.utils.router import route
from django.shortcuts import render
from django.http import HttpResponse, HttpRequest
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from bloomerp.models import Workspace

@login_required
@require_POST
@route('reset_workspace')
def reset_workspace(request:HttpRequest) -> HttpResponse:
    '''Component that resets a workspace to it's default state.
    
    POST Args:
        workspace_id (int): The id of the workspace to reset.
    '''
    # Permissions check
    if not request.user.has_perm('bloomerp.change_workspace'):
        return HttpResponse('User does not have permission to view work', status=200)

    workspace_id = request.POST.get('workspace_id')

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except:
        return HttpResponse('Invalid workspace id', status=200)
    
    # Reset the workspace
    if workspace.content_type:
        workspace.content = Workspace.create_default_content_type_workspace(
            user=request.user,
            content_type=workspace.content_type,
            commit=False
        ).content
    else:
        workspace.content = Workspace.create_default_workspace(
            user=request.user,
            commit=False
        ).content

    workspace.save()
    
    return HttpResponse('Workspace reset successfully', status=200)