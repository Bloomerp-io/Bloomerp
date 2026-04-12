import json
from django.urls import reverse
from django import forms
from django.shortcuts import redirect
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router
from bloomerp.services.workspace_services import ensure_default_workspace_tiles_for_module
from bloomerp.utils.models import get_create_view_url
from bloomerp.views.mixins import HtmxMixin
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from bloomerp.modules.definition import module_registry
from django.views.generic.edit import FormView


def _build_module_choices():
    return [("", "General workspace")] + [
        (module.id, module.name)
        for module in module_registry.get_all().values()
    ]


def _build_submodule_map() -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for module in module_registry.get_all().values():
        result[module.id] = [
            {"id": sub_module.id, "name": sub_module.name}
            for sub_module in module.sub_modules
        ]
    return result


def _derive_module_id_from_submodule(sub_module_id: str | None) -> str | None:
    if not sub_module_id:
        return None

    for module in module_registry.get_all().values():
        if any(sub_module.id == sub_module_id for sub_module in module.sub_modules):
            return module.id

    return None


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
    sub_module_id = forms.ChoiceField(
        required=False,
        choices=[("", "All submodules")],
        widget=forms.Select(attrs={"class": "input", "data-workspace-submodule-select": "true"}),
    )
    generate_default = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
    )

    def __init__(self, *args, fixed_module_id: str | None = None, fixed_sub_module_id: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_module_id = fixed_module_id or None
        self.fixed_sub_module_id = fixed_sub_module_id or None
        self.submodule_map = _build_submodule_map()

        self.fields["module_id"].choices = _build_module_choices()

        effective_module_id = self.fixed_module_id or self.data.get("module_id") or self.initial.get("module_id") or ""
        effective_submodule_id = self.fixed_sub_module_id or self.data.get("sub_module_id") or self.initial.get("sub_module_id") or ""

        if effective_module_id and effective_module_id in self.submodule_map:
            self.fields["sub_module_id"].choices = [("", "All submodules")] + [
                (item["id"], item["name"])
                for item in self.submodule_map[effective_module_id]
            ]
        else:
            self.fields["sub_module_id"].choices = [("", "All submodules")]

        self.initial.setdefault("module_id", effective_module_id)
        self.initial.setdefault("sub_module_id", effective_submodule_id)

    def clean(self):
        cleaned_data = super().clean()

        module_id = self.fixed_module_id or cleaned_data.get("module_id") or ""
        sub_module_id = self.fixed_sub_module_id or cleaned_data.get("sub_module_id") or ""

        if sub_module_id and not module_id:
            derived_module_id = _derive_module_id_from_submodule(sub_module_id)
            if not derived_module_id:
                self.add_error("sub_module_id", "Invalid submodule selection.")
            else:
                module_id = derived_module_id

        if module_id and sub_module_id:
            valid_submodules = {item["id"] for item in self.submodule_map.get(module_id, [])}
            if sub_module_id not in valid_submodules:
                self.add_error("sub_module_id", "Selected submodule does not belong to the selected module.")

        cleaned_data["module_id"] = module_id
        cleaned_data["sub_module_id"] = sub_module_id
        cleaned_data["generate_default"] = bool(cleaned_data.get("generate_default")) and bool(module_id)
        return cleaned_data

@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    models=[Workspace],
    override=True
)
class CreateWorkspaceView(LoginRequiredMixin, PermissionRequiredMixin, HtmxMixin, FormView):
    model = Workspace
    template_name = "workspace_views/create_workspace_view.html"
    form_class = CreateWorkspaceForm
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["url"] = self.request.get_full_path()
        fixed_module_id = self.get_fixed_module_id()
        fixed_sub_module_id = self.get_fixed_sub_module_id()
        ctx["fixed_module_id"] = fixed_module_id or ""
        ctx["fixed_sub_module_id"] = fixed_sub_module_id or ""
        ctx["submodule_map_json"] = json.dumps(_build_submodule_map())
        ctx["show_module_field"] = not fixed_module_id and not fixed_sub_module_id
        ctx["show_submodule_field"] = bool(fixed_module_id and not fixed_sub_module_id) or bool(
            (self.request.POST.get("module_id") or self.request.GET.get("module_id")) and not fixed_sub_module_id
        )
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["fixed_module_id"] = self.get_fixed_module_id()
        kwargs["fixed_sub_module_id"] = self.get_fixed_sub_module_id()
        return kwargs

    def form_valid(self, form):
        module_id = form.cleaned_data.get("module_id") or ""
        sub_module_id = form.cleaned_data.get("sub_module_id") or ""
        generate_default = form.cleaned_data.get("generate_default", False)

        workspace = Workspace.objects.create(
            user=self.request.user,
            name=form.cleaned_data["name"],
            module_id=module_id,
            sub_module_id=sub_module_id,
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
        if self.request.GET.get("module_id"):
            return self.request.GET.get("module_id")
        fixed_sub_module_id = self.get_fixed_sub_module_id()
        if fixed_sub_module_id:
            return _derive_module_id_from_submodule(fixed_sub_module_id)
        return None

    def get_fixed_sub_module_id(self) -> str | None:
        return self.request.GET.get("sub_module_id") or None
    
    
