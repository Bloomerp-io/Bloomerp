import json

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import redirect
from django.views.generic.edit import FormView
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.modules.definition import module_registry
from bloomerp.router import router
from bloomerp.services.workspace_services import ensure_default_workspace_tiles_for_module
from bloomerp.utils.models import get_create_view_url
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.conditional_staff_required_mixin import ConditionalStaffRequiredMixin
from bloomerp.views.mixins.htmx_mixin import HtmxMixin


def _module_choice_label(module) -> str:
    lineage = module_registry.get_lineage(module.full_id or module.id)
    return " / ".join(item.name for item in lineage) if lineage else module.name


def _build_module_choices():
    return [("", "General workspace")] + [
        (module.full_id or module.id, _module_choice_label(module))
        for module in sorted(module_registry.get_all().values(), key=lambda item: (item.depth, item.route_path or item.id))
    ]


class CreateWorkspaceForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Workspace name"}),
    )
    module_id = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "input", "data-workspace-module-select": "true"}),
    )
    generate_default = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
    )

    def __init__(self, *args, fixed_module_id: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_module_id = fixed_module_id or None
        self.fields["module_id"].choices = _build_module_choices()
        effective_module_id = self.fixed_module_id or self.data.get("module_id") or self.initial.get("module_id") or ""
        self.initial.setdefault("module_id", effective_module_id)

    def clean(self):
        cleaned_data = super().clean()
        module_id = self.fixed_module_id or cleaned_data.get("module_id") or ""
        if module_id and module_registry.get(module_id) is None:
            self.add_error("module_id", "Invalid module selection.")
        cleaned_data["module_id"] = module_id
        cleaned_data["generate_default"] = bool(cleaned_data.get("generate_default")) and bool(module_id)
        return cleaned_data


@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    models=[Workspace],
    override=True,
)
class CreateWorkspaceView(BaseBloomerpView, FormView):
    model = Workspace
    template_name = "workspace_views/create_workspace_view.html"
    form_class = CreateWorkspaceForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        fixed_module_id = self.get_fixed_module_id()
        ctx["url"] = self.request.get_full_path()
        ctx["fixed_module_id"] = fixed_module_id or ""
        ctx["show_module_field"] = not fixed_module_id
        ctx["module_choices_json"] = json.dumps(
            [{"id": module.id, "label": _module_choice_label(module)} for module in module_registry.get_all().values()]
        )
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["fixed_module_id"] = self.get_fixed_module_id()
        return kwargs

    def form_valid(self, form):
        module_id = form.cleaned_data.get("module_id") or ""
        generate_default = form.cleaned_data.get("generate_default", False)

        workspace = Workspace.objects.create(
            user=self.request.user,
            name=form.cleaned_data["name"],
            module_id=module_id,
            is_default=False,
            layout={"rows": [{"title": None, "columns": 4, "items": []}]},
        )

        if generate_default and module_id:
            ensure_default_workspace_tiles_for_module(self.request.user, module_id)

        if self.request.htmx:
            return HttpResponseClientRedirect(workspace.get_absolute_url())
        return redirect(workspace.get_absolute_url())

    def get_htmx_include_addendum(self):
        if self.request.htmx and self.request.htmx.target != "main-content":
            return False
        return super().get_htmx_include_addendum()

    def has_permission(self):
        return True

    def get_fixed_module_id(self) -> str | None:
        return self.request.GET.get("module_id") or None
