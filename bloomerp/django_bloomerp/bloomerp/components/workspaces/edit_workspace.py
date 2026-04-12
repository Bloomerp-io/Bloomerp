from django import forms
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router


class EditWorkspaceForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Workspace name"}),
    )


@router.register(
    path="components/workspaces/<int:workspace_id>/edit/",
    name="components_workspaces_edit_workspace",
)
def edit_workspace(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """Component to edit a particular workspace

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
        form = EditWorkspaceForm(request.POST)
        if form.is_valid():
            workspace.name = form.cleaned_data["name"]
            workspace.save(update_fields=["name"])
            redirect_url = reverse("my_workspaces")
            if request.htmx:
                return HttpResponseClientRedirect(redirect_url)
            return redirect(redirect_url)
    else:
        form = EditWorkspaceForm(initial={"name": workspace.name})

    return render(
        request,
        "components/workspaces/edit_workspace.html",
        {
            "form": form,
            "workspace": workspace,
            "submit_url": reverse("components_workspaces_edit_workspace", kwargs={"workspace_id": workspace.id}),
        },
    )
