from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.views.generic.edit import CreateView
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth import get_user_model
from django.contrib.messages.views import SuccessMessageMixin
from bloomerp.models.files import File
from bloomerp.models.workspaces import Tile, SqlQuery
from bloomerp.models import UserCreateViewPreference
from bloomerp.services.create_view_services import (
    get_create_access_state,
    get_disallowed_submitted_fields,
)
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import resolve_create_layout_rows
from bloomerp.utils.models import model_name_plural_underline, get_detail_view_url
from bloomerp.views.mixins import BloomerpModelFormViewMixin, HtmxMixin
from bloomerp.router import router


User = get_user_model()

# TODO: We want to have a button that allows us to hide non required fields.

@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    exclude_models=[File, Tile, SqlQuery, User],
)
class BloomerpCreateView(
    PermissionRequiredMixin,
    SuccessMessageMixin,
    HtmxMixin,
    BloomerpModelFormViewMixin,
    CreateView,
):
    template_name = "create_views/bloomerp_create_view.html"
    fields = None
    exclude = []
    success_message = "Object was created successfully."
    module = None
    model = None

    def get_form_hx_target(self) -> str:
        return "#main-content"

    def get_form_hx_push_url(self) -> bool:
        return True

    def get_non_required_fields_visible_default(self) -> bool:
        return True

    def get_non_required_fields_visible_attr(self) -> str:
        return "true" if self.get_non_required_fields_visible_default() else "false"

    def get_full_form_url(self) -> str | None:
        return None

    def dispatch(self, request, *args, **kwargs):
        self.model_content_type = ContentType.objects.get_for_model(self.model)
        self.create_access_state = get_create_access_state(content_type=self.model_content_type, user=request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get("form") or self.get_form()

        context["content_type_id"] = self.model_content_type.pk
        context["create_blocked"] = self.create_access_state.is_blocked
        context["create_blocked_message"] = self.create_access_state.blocked_message

        
        preference = UserCreateViewPreference.get_or_create_for_user(self.request.user, self.model_content_type)
        layout = {
            "rows": resolve_create_layout_rows(
                layout=preference.field_layout_obj,
                content_type=self.model_content_type,
                user=self.request.user,
                form=form,
            )
        }
        if not any(row.get("items") for row in layout["rows"]):
            preference.field_layout = self._build_fallback_layout().model_dump()
            preference.save(update_fields=["field_layout"])
            layout = {
                "rows": resolve_create_layout_rows(
                    layout=preference.field_layout_obj,
                    content_type=self.model_content_type,
                    user=self.request.user,
                    form=form,
                )
            }

        context["layout"] = layout
        context["layout_available_items_url"] = f"/components/workspaces/crud_layout_available_fields/?content_type_id={self.model_content_type.pk}&layout_kind=create"
        context["layout_render_item_url"] = "/components/workspaces/crud_layout_render_field/?layout_kind=create"
        context["form_hx_target"] = self.get_form_hx_target()
        context["form_hx_push_url"] = self.get_form_hx_push_url()
        context["non_required_fields_visible"] = self.get_non_required_fields_visible_default()
        context["non_required_fields_visible_attr"] = self.get_non_required_fields_visible_attr()
        context["full_form_url"] = self.get_full_form_url()
        context["hidden_initial_fields"] = self.get_hidden_initial_fields(layout=layout, form=form)
        return context

    def get_success_message(self, cleaned_data):
        return f"{self.object} was created successfully."

    def get_success_url(self):
        try:
            return self.object.get_absolute_url()
        except AttributeError:
            return reverse(get_detail_view_url(self.object), kwargs={"pk": self.object.pk})

    def get_form_class(self):
        allowed_field_names = [field.field for field in self.create_access_state.addable_fields]
        return super().get_form_class_for_fields(allowed_field_names)

    def get_initial(self):
        initial = super().get_initial()
        allowed_field_names = {field.field for field in self.create_access_state.addable_fields}
        for key, value in self.request.GET.items():
            if key in allowed_field_names:
                initial[key] = value
        return initial

    def post(self, request, *args, **kwargs):
        if self.create_access_state.is_blocked:
            form = self.get_form()
            form.add_error(None, self.create_access_state.blocked_message)
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        allowed_field_names = {field.field for field in self.create_access_state.addable_fields}
        denied_fields = get_disallowed_submitted_fields(
            model=self.model,
            submitted_data=self.request.POST,
            allowed_field_names=allowed_field_names,
        )
        if denied_fields:
            form.add_error(None, f"Permission denied for fields: {', '.join(denied_fields)}")
            return self.form_invalid(form)

        permission_manager = UserPermissionManager(self.request.user)
        add_permission = create_permission_str(self.model, "add")
        if not permission_manager.candidate_matches_row_policies(self.model, add_permission, form.cleaned_data):
            form.add_error(None, "You do not have permission to create an object with these values.")
            return self.form_invalid(form)

        return super().form_valid(form)

    def _build_fallback_layout(self):
        from bloomerp.services.create_view_services import get_default_layout

        return get_default_layout(content_type=self.model_content_type, user=self.request.user)

    def get_hidden_initial_fields(self, *, layout: dict, form) -> list[tuple[str, str]]:
        # TODO: Check that the fields are filled EVEN when the fields are not on the actual form.
        
        layout_field_names = {
            item["application_field"].field
            for row in layout.get("rows", [])
            for item in row.get("items", [])
            if item.get("application_field") is not None
        }
        hidden_fields: list[tuple[str, str]] = []

        for field_name, value in self.get_initial().items():
            if field_name not in form.fields:
                continue
            if field_name in layout_field_names:
                continue
            hidden_fields.append((field_name, value))

        return hidden_fields

    def has_permission(self):
        manager = UserPermissionManager(self.request.user)    

        return manager.has_global_permission(
            self.model, 
            create_permission_str(self.model, "add")
            )