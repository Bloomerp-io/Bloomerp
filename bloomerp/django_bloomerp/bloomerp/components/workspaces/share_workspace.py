from django import forms
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class WorkspaceShareForm(forms.Form):
    shared_with = forms.ModelMultipleChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        label=_("Shared with"),
        help_text=_("Search and add users who should be able to open this workspace."),
        widget=ForeignFieldWidget(
            attrs={
                "model": get_user_model(),
                "is_m2m": True,
                "class": "input h-11 w-full",
            }
        ),
    )

    def __init__(self, *args, workspace: Workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["shared_with"].queryset = get_user_model().objects.exclude(pk=workspace.user_id).order_by("username")


def _get_owned_workspace(request: HttpRequest, workspace_id: int) -> Workspace | HttpResponse:
    workspace = get_object_or_404(Workspace, pk=workspace_id)
    if workspace.user_id != request.user.pk:
        return HttpResponse("Permission denied", status=403)
    return workspace


@router.register(
    path="components/workspaces/share/<int:workspace_id>/",
    name="components_workspaces_share_workspace",
)
def share_workspace(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """Component to share workspaces

    Args:
        request (HttpRequest): 
        workspace_id (int): the workspace id

    Returns:
        HttpResponse: 
    """
    workspace = _get_owned_workspace(request, workspace_id)
    if isinstance(workspace, HttpResponse):
        return workspace

    initial = {
        "shared_with": workspace.shared_with.all(),
    }
    form = WorkspaceShareForm(workspace=workspace, initial=initial)
    success = False

    if request.method == "POST":
        form = WorkspaceShareForm(request.POST, workspace=workspace)
        if form.is_valid():
            workspace.shared_with.set(form.cleaned_data["shared_with"])
            form = WorkspaceShareForm(workspace=workspace, initial={"shared_with": workspace.shared_with.all()})
            success = True

    return render(
        request,
        "components/workspaces/share_workspace.html",
        {
            "workspace": workspace,
            "form": form,
            "success": success,
        },
    )
