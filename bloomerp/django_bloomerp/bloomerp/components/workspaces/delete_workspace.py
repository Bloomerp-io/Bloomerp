from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router


@router.register(
    path="components/workspaces/<int:workspace_id>/delete/",
    name="components_workspaces_delete_workspace",
)
def delete_workspace(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """Component to delete a workspace

    Args:
        request (HttpRequest): 
        workspace_id (int): the workspace id

    Returns:
        HttpResponse: 
    """

    workspace = get_object_or_404(Workspace, pk=workspace_id)
    if workspace.user_id != request.user.id:
        return HttpResponse("Permission denied", status=403)

    if request.method == "POST":
        workspace.delete()
        redirect_url = reverse("my_workspaces")
        if request.htmx:
            return HttpResponseClientRedirect(redirect_url)
        return redirect(redirect_url)

    return render(
        request,
        "components/workspaces/delete_workspace.html",
        {
            "workspace": workspace,
            "submit_url": reverse("components_workspaces_delete_workspace", kwargs={"workspace_id": workspace.id}),
        },
    )
